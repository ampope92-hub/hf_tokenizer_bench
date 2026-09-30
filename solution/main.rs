use std::collections::{BTreeMap, HashMap};
use std::fs;
use tokenizers::{Tokenizer, TruncationParams, TruncationStrategy, TruncationDirection,
                 PaddingParams, PaddingStrategy, PaddingDirection, EncodeInput,
                 FromPretrainedParameters};
use serde_json::{json, Value};

fn round6(x: f64) -> f64 {
    (x * 1e6 + 0.5).floor() / 1e6
}

fn main() {
    let dir = std::env::args().nth(1).unwrap_or_else(|| "/app/cases".to_string());
    let mut paths: Vec<_> = fs::read_dir(&dir).unwrap().filter_map(|e| e.ok()).map(|e| e.path())
        .filter(|p| p.extension().map(|x| x == "json").unwrap_or(false)).collect();
    paths.sort();

    // Keyed by (repo, revision): the case names the commit to load, so two cases naming the
    // same repo at different commits are two different tokenizers.
    let mut cache: BTreeMap<(String, String), Tokenizer> = BTreeMap::new();
    let mut out = Vec::new();
    let (mut total, mut total_content, mut total_words) = (0u64, 0u64, 0u64);
    let (mut pass, mut warn, mut fail) = (0u64, 0u64, 0u64);

    for p in &paths {
        let c: Value = serde_json::from_str(&fs::read_to_string(p).unwrap()).unwrap();
        let model = c["model"].as_str().unwrap().to_string();
        let revision = c["revision"].as_str().unwrap().to_string();
        let key = (model.clone(), revision.clone());
        let tok = cache.entry(key).or_insert_with(|| {
            // Pull the tokenizer at the commit the case names rather than at whatever the
            // repo's default branch happens to be today.
            let params = FromPretrainedParameters { revision, ..Default::default() };
            Tokenizer::from_pretrained(&model, Some(params)).unwrap()
        });

        match c.get("max_length").and_then(|v| v.as_u64()) {
            Some(max) => {
                let strat = match c.get("truncation").and_then(|v| v.as_str()) {
                    Some("only_first") => TruncationStrategy::OnlyFirst,
                    Some("only_second") => TruncationStrategy::OnlySecond,
                    _ => TruncationStrategy::LongestFirst,
                };
                tok.with_truncation(Some(TruncationParams { max_length: max as usize, strategy: strat,
                    stride: 0, direction: TruncationDirection::Right })).unwrap();
            }
            None => { tok.with_truncation(None).unwrap(); }
        }
        match c.get("padding").and_then(|v| v.as_u64()) {
            Some(padlen) => { tok.with_padding(Some(PaddingParams {
                strategy: PaddingStrategy::Fixed(padlen as usize), direction: PaddingDirection::Right,
                pad_to_multiple_of: None, pad_id: 0, pad_type_id: 0, pad_token: "[PAD]".into() })); }
            None => { tok.with_padding(None); }
        }

        let add = c["add_special_tokens"].as_bool().unwrap_or(true);
        let text_a = c["text_a"].as_str().unwrap();
        let text_b = c.get("text_b").and_then(|v| v.as_str());
        let enc = match text_b {
            Some(b) => { let inp: EncodeInput = (text_a, b).into(); tok.encode(inp, add).unwrap() }
            None => tok.encode(text_a, add).unwrap(),
        };

        // Word-level analysis: content tokens have a non-null word id; a word is a distinct
        // (sequence id, word id) pair.
        let word_ids = enc.get_word_ids();
        let seq_ids = enc.get_sequence_ids();
        let mut groups: HashMap<(usize, u32), u64> = HashMap::new();
        let mut content: u64 = 0;
        for i in 0..word_ids.len() {
            if let Some(w) = word_ids[i] {
                content += 1;
                let s = seq_ids[i].unwrap_or(0);
                *groups.entry((s, w)).or_insert(0) += 1;
            }
        }
        let word_count = groups.len() as u64;
        let split_words = groups.values().filter(|&&n| n >= 2).count() as u64;
        let max_word_tokens = groups.values().copied().max().unwrap_or(0);

        let chars = text_a.chars().count() as u64 + text_b.map(|b| b.chars().count() as u64).unwrap_or(0);
        let raw_fertility = if word_count > 0 { Some(content as f64 / word_count as f64) } else { None };
        let compression = if content > 0 { Some(round6(chars as f64 / content as f64)) } else { None };

        let p_thr = c["fertility_pass"].as_f64().unwrap();
        let w_thr = c["fertility_warn"].as_f64().unwrap();
        let status = match raw_fertility {
            None => "pass",
            Some(f) if f <= p_thr => "pass",
            Some(f) if f <= w_thr => "warn",
            Some(_) => "fail",
        };
        match status { "pass" => pass += 1, "warn" => warn += 1, _ => fail += 1 }

        total += enc.get_ids().len() as u64;
        total_content += content;
        total_words += word_count;

        let offs: Vec<Vec<usize>> = enc.get_offsets().iter().map(|(a, b)| vec![*a, *b]).collect();
        out.push(json!({
            "name": c["name"], "model": model, "n_tokens": enc.get_ids().len(),
            "ids": enc.get_ids(), "tokens": enc.get_tokens(), "type_ids": enc.get_type_ids(),
            "attention_mask": enc.get_attention_mask(),
            "special_tokens_mask": enc.get_special_tokens_mask(), "offsets": offs,
            "content_tokens": content, "word_count": word_count, "split_words": split_words,
            "max_word_tokens": max_word_tokens,
            "fertility": raw_fertility.map(round6),
            "compression": compression,
            "status": status,
        }));
    }

    let corpus = if total_words > 0 { Some(round6(total_content as f64 / total_words as f64)) } else { None };
    let report = json!({"cases": out, "summary": {
        "case_count": paths.len(), "total_tokens": total,
        "total_content_tokens": total_content, "total_words": total_words,
        "corpus_fertility": corpus, "pass": pass, "warn": warn, "fail": fail,
    }});
    println!("{}", serde_json::to_string(&report).unwrap());
}
