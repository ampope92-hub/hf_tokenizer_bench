// hf_tokenize: read tokenization cases from a directory, run each through its Hugging Face
// tokenizer, and print the JSON report described in the task to stdout.
//
// This is a stub: it compiles and runs but does no real work yet. Implement it to spec.
fn main() {
    let _dir = std::env::args().nth(1).unwrap_or_else(|| "/app/cases".to_string());
    println!("{{\"cases\":[],\"summary\":{{\"case_count\":0,\"total_tokens\":0}}}}");
}
