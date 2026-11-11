use qbo_mcp_keepalive::*;
use serde_json::{json, Value};
use std::time::{Duration, Instant};
#[tokio::test]
async fn fixture_driver() {
    let Ok(path) = std::env::var("FIXTURE_INPUT") else {
        return;
    };
    let input: Value = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
    let wait = Duration::from_secs_f64(input["timeout"].as_f64().unwrap_or(1.0));
    let mut builder = reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .read_timeout(wait);
    if let Some(path) = input["certificate"].as_str() {
        builder = builder.add_root_certificate(
            reqwest::Certificate::from_pem(&std::fs::read(path).unwrap()).unwrap(),
        );
    }
    let external = builder.build().unwrap();
    let local = client(wait, false).unwrap();
    let started = Instant::now();
    let output = match input["op"].as_str().unwrap() {
        "diagnostics" => json!(input["replies"]
            .as_array()
            .unwrap()
            .iter()
            .map(|reply| company_result("fixture", "Synthetic company", reply, 0.0))
            .collect::<Vec<_>>()),
        "company" => json!(
            check_company(
                &local,
                "fixture",
                input["port"].as_u64().unwrap() as u16,
                "Synthetic company",
                wait,
                false
            )
            .await
        ),
        "gate" => json!(check_gate(&external, input["host"].as_str().unwrap(), "fixture").await),
        "slack" => json!(
            slack(&external, input["webhook"].as_str(), "synthetic message")
                .await
                .err()
        ),
        "notification" => json!(notification(
            input["ok"].as_bool().unwrap(),
            input["heartbeat"].as_bool().unwrap(),
            "2026-11-11",
            "synthetic report"
        )),
        _ => panic!("Unknown fixture"),
    };
    std::fs::write(
        std::env::var("FIXTURE_OUTPUT").unwrap(),
        serde_json::to_vec(
            &json!({"result":output,"elapsed_ms":started.elapsed().as_secs_f64()*1000.0}),
        )
        .unwrap(),
    )
    .unwrap();
}
