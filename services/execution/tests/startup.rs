//! The paper-only guard (spec 7.4): the binary must refuse to start against any non-paper endpoint.

use std::process::Command;

fn run_with(url: &str) -> std::process::Output {
    Command::new(env!("CARGO_BIN_EXE_arena-execution"))
        .env("ALPACA_TRADING_BASE_URL", url)
        .env("EXECUTION_BIND", "127.0.0.1:0")
        .env_remove("ARENA_ENV")
        .output()
        .unwrap()
}

#[test]
fn exits_nonzero_for_the_live_endpoint() {
    let out = run_with("https://api.alpaca.markets");
    assert!(!out.status.success());
    assert!(String::from_utf8_lossy(&out.stdout).contains("refusing to start"));
}

#[test]
fn exits_nonzero_for_any_other_url() {
    assert!(!run_with("http://localhost:9999").status.success());
}
