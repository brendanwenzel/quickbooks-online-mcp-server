use chrono::{Datelike, Local};
use qbo_mcp_keepalive::{check_company, check_gate, client, notification, slack};
use serde_json::Value;
use std::{env, time::Duration};
fn integer(value: &Value) -> Option<i64> {
    match value {
        Value::Bool(v) => Some(i64::from(*v)),
        Value::Number(v) => v
            .as_i64()
            .or_else(|| v.as_f64().filter(|v| v.is_finite()).map(|v| v as i64)),
        Value::String(v) => v.trim().parse().ok(),
        _ => None,
    }
}
async fn run() -> Result<i32, String> {
    if env::args().len() != 1 {
        return Err(
            "This watchdog accepts configuration through its existing environment only".into(),
        );
    }
    let path = env::var_os("QBO_KEEPALIVE_CONFIG")
        .unwrap_or_else(|| "/etc/quickbooks-mcp/keepalive.json".into());
    let cfg: Value =
        serde_json::from_slice(&std::fs::read(path).map_err(|_| "Configuration unavailable")?)
            .map_err(|_| "Invalid configuration JSON")?;
    let seconds: f64 = env::var("QBO_KEEPALIVE_TIMEOUT")
        .unwrap_or_else(|_| "60".into())
        .parse()
        .map_err(|_| "Invalid timeout")?;
    if !seconds.is_finite() || seconds <= 0.0 || seconds > 86400.0 {
        return Err("Invalid timeout".into());
    }
    let wait = Duration::from_secs_f64(seconds);
    let local = client(wait, false)?;
    let external = client(Duration::from_secs(30), true)?;
    let mut lines = Vec::new();
    let mut ok = true;
    for target in cfg["targets"].as_array().ok_or("Invalid target list")? {
        let slug = target["slug"].as_str().ok_or("Invalid target slug")?;
        let expect = target["expect"].as_str().ok_or("Invalid company name")?;
        let port = integer(&target["port"])
            .and_then(|v| u16::try_from(v).ok())
            .ok_or("Invalid target port")?;
        let (good, message) = check_company(
            &local,
            slug,
            port,
            expect,
            wait,
            env::var("QBO_KEEPALIVE_VERBOSE").as_deref() == Ok("1"),
        )
        .await;
        ok &= good;
        lines.push(format!("{} {message}", if good { "✅" } else { "❌" }));
        if let Some(host) = cfg["public_host"].as_str().filter(|v| !v.is_empty()) {
            let (good, message) = check_gate(&external, host, slug).await;
            ok &= good;
            lines.push(format!("{} {message}", if good { "✅" } else { "❌" }));
        }
    }
    let report = lines.join("\n");
    println!("{report}");
    let today = Local::now().date_naive();
    if !cfg["heartbeat_weekday"].is_null()
        && integer(&cfg["heartbeat_weekday"]).is_none()
        && env::var("QBO_KEEPALIVE_HEARTBEAT").as_deref() != Ok("1")
    {
        return Err("Invalid heartbeat weekday".into());
    }
    let heartbeat = env::var("QBO_KEEPALIVE_HEARTBEAT").as_deref() == Ok("1")
        || integer(&cfg["heartbeat_weekday"])
            == Some(today.weekday().num_days_from_monday().into());
    if let Some(text) = notification(ok, heartbeat, &today.to_string(), &report) {
        slack(
            &external,
            env::var("SLACK_WEBHOOK_URL").ok().as_deref(),
            &text,
        )
        .await?;
    }
    Ok(if ok { 0 } else { 1 })
}
#[tokio::main]
async fn main() {
    match run().await {
        Ok(code) => std::process::exit(code),
        Err(error) => {
            eprintln!("keepalive: {error}");
            std::process::exit(1)
        }
    }
}
