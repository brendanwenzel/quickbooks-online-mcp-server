//! Read-only MCP identity watchdog. Notification policy matches the maintained host script.
use futures_util::StreamExt;
use reqwest::{Client, Response};
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    time::{Duration, Instant},
};
use tokio::{sync::mpsc, task::JoinHandle, time::timeout};

type Result<T> = std::result::Result<T, String>;
enum Event {
    Endpoint(String),
    Message(i64, Value),
}
struct Session {
    client: Client,
    base: String,
    endpoint: String,
    incoming: mpsc::Receiver<Event>,
    replies: HashMap<i64, Value>,
    pump: JoinHandle<()>,
}
impl Drop for Session {
    fn drop(&mut self) {
        self.pump.abort();
    }
}
fn py_space(c: char) -> bool {
    c.is_whitespace() || matches!(c, '\u{1c}'..='\u{1f}')
}
fn transport(error: reqwest::Error) -> String {
    if error.is_timeout() {
        "request timed out".into()
    } else if error.is_connect() {
        "connection failed".into()
    } else {
        "HTTP transport failed".into()
    }
}
async fn pump(response: Response, prefix: String, sender: mpsc::Sender<Event>, wait: Duration) {
    let mut stream = response.bytes_stream();
    let mut pending = Vec::new();
    let mut event = String::new();
    let mut endpoint = false;
    while let Ok(Some(Ok(bytes))) = timeout(wait, stream.next()).await {
        pending.extend_from_slice(&bytes);
        if pending.len() > 1024 * 1024 {
            break;
        }
        while let Some(end) = pending.iter().position(|v| *v == b'\n') {
            let raw: Vec<_> = pending.drain(..=end).collect();
            let line = String::from_utf8_lossy(&raw);
            let line = line.trim_end_matches(['\r', '\n']);
            if let Some(value) = line.strip_prefix("event:") {
                event = value.trim_matches(py_space).into();
            } else if let Some(value) = line.strip_prefix("data:") {
                let data = value.trim_matches(py_space);
                let item = if event == "endpoint" || (!endpoint && data.starts_with('/')) {
                    let mut path = if data.starts_with('/') {
                        data.to_owned()
                    } else {
                        let remainder = data.split_once("://").map_or(data, |(_, v)| v);
                        format!(
                            "/{}",
                            remainder.split_once('/').map_or(remainder, |(_, v)| v)
                        )
                    };
                    if path.starts_with(&format!("{prefix}/")) {
                        path = path[prefix.len()..].into();
                    }
                    endpoint = true;
                    Some(Event::Endpoint(path))
                } else {
                    serde_json::from_str::<Value>(data).ok().and_then(|v| {
                        v.get("id")
                            .and_then(Value::as_i64)
                            .filter(|id| matches!(id, 1 | 2))
                            .map(|id| Event::Message(id, v.clone()))
                    })
                };
                if let Some(item) = item {
                    if sender.send(item).await.is_err() {
                        return;
                    }
                }
            } else if line.is_empty() {
                event.clear();
            }
        }
    }
}
impl Session {
    async fn open(client: Client, port: u16, slug: &str, wait: Duration) -> Result<Self> {
        let base = format!("http://127.0.0.1:{port}");
        let response = client
            .get(format!("{base}/sse"))
            .header("Accept", "text/event-stream")
            .send()
            .await
            .map_err(transport)?;
        if response.status() != 200 {
            return Err(format!("GET /sse -> HTTP {}", response.status().as_u16()));
        }
        let (tx, rx) = mpsc::channel(8);
        let task = tokio::spawn(pump(response, format!("/{slug}"), tx, wait));
        let mut session = Self {
            client,
            base,
            endpoint: String::new(),
            incoming: rx,
            replies: HashMap::new(),
            pump: task,
        };
        let found = timeout(wait, async {
            while let Some(event) = session.incoming.recv().await {
                match event {
                    Event::Endpoint(value) => return Some(value),
                    Event::Message(id, value) => {
                        session.replies.insert(id, value);
                    }
                }
            }
            None
        })
        .await;
        session.endpoint = found.ok().flatten().ok_or("no endpoint event from /sse")?;
        Ok(session)
    }
    async fn post(&self, value: Value, wait: Duration) -> Result<()> {
        // The advertised endpoint remains a path on the configured local container.
        let response = self
            .client
            .post(format!("{}{}", self.base, self.endpoint))
            .timeout(wait)
            .json(&value)
            .send()
            .await
            .map_err(transport)?;
        let status = response.status().as_u16();
        response.bytes().await.map_err(transport)?;
        if status != 200 && status != 202 {
            return Err(format!(
                "POST {} -> HTTP {status}",
                self.endpoint.split('?').next().unwrap_or("/")
            ));
        }
        Ok(())
    }
    async fn wait(&mut self, id: i64, wait: Duration) -> Result<Value> {
        let found = timeout(wait, async {
            loop {
                if let Some(value) = self.replies.remove(&id) {
                    return Some(value);
                }
                match self.incoming.recv().await? {
                    Event::Message(key, value) => {
                        self.replies.insert(key, value);
                    }
                    Event::Endpoint(value) => self.endpoint = value,
                }
            }
        })
        .await;
        found.ok().flatten().ok_or_else(|| {
            format!(
                "no response to request {id} within {:.0}s",
                wait.as_secs_f64()
            )
        })
    }
}
pub fn client(wait: Duration, redirects: bool) -> Result<Client> {
    let builder = if redirects {
        Client::builder()
    } else {
        Client::builder().no_proxy()
    };
    builder
        .connect_timeout(wait)
        .read_timeout(wait)
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(transport)
}
fn truth(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(v) => *v,
        Value::Number(v) => v.as_f64() != Some(0.0),
        Value::String(v) => !v.is_empty(),
        Value::Array(v) => !v.is_empty(),
        Value::Object(v) => !v.is_empty(),
    }
}
fn error_json(value: &Value) -> String {
    match value {
        Value::Array(items) => format!(
            "[{}]",
            items.iter().map(error_json).collect::<Vec<_>>().join(", ")
        ),
        Value::Object(items) => format!(
            "{{{}}}",
            items
                .iter()
                .map(|(key, value)| format!("{}: {}", error_json(&json!(key)), error_json(value)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
        Value::String(_) => value
            .to_string()
            .chars()
            .map(|c| {
                if c.is_ascii() && c != '\u{7f}' {
                    c.to_string()
                } else {
                    c.encode_utf16(&mut [0; 2])
                        .iter()
                        .map(|u| format!("\\u{u:04x}"))
                        .collect()
                }
            })
            .collect(),
        _ => value.to_string(),
    }
}
fn nonprintable(c: char) -> bool {
    use unicode_general_category::{get_general_category as category, GeneralCategory::*};
    c != ' '
        && matches!(
            category(c),
            Control
                | Format
                | LineSeparator
                | ParagraphSeparator
                | SpaceSeparator
                | PrivateUse
                | Unassigned
                | Surrogate
        )
}
fn repr(value: &Value) -> String {
    match value {
        Value::Null => "None".into(),
        Value::Bool(value) => if *value { "True" } else { "False" }.into(),
        Value::Array(items) => format!(
            "[{}]",
            items.iter().map(repr).collect::<Vec<_>>().join(", ")
        ),
        Value::Object(items) => format!(
            "{{{}}}",
            items
                .iter()
                .map(|(key, value)| format!("{}: {}", repr(&json!(key)), repr(value)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
        Value::String(s) => {
            let quote = if s.contains('\'') && !s.contains('"') {
                '"'
            } else {
                '\''
            };
            let mut out = quote.to_string();
            for c in s.chars() {
                match c {
                    '\\' => out.push_str("\\\\"),
                    '\n' => out.push_str("\\n"),
                    '\r' => out.push_str("\\r"),
                    '\t' => out.push_str("\\t"),
                    v if nonprintable(v) => {
                        let code = v as u32;
                        out.push_str(&if code <= 255 {
                            format!("\\x{code:02x}")
                        } else if code <= 65535 {
                            format!("\\u{code:04x}")
                        } else {
                            format!("\\U{code:08x}")
                        });
                    }
                    v if v == quote => {
                        out.push('\\');
                        out.push(v)
                    }
                    v => out.push(v),
                }
            }
            out.push(quote);
            out
        }
        v => v.to_string(),
    }
}
pub fn company_result(slug: &str, expect: &str, reply: &Value, elapsed: f64) -> (bool, String) {
    let result = reply.get("result").filter(|v| truth(v));
    if result
        .and_then(|v| v.get("content"))
        .and_then(Value::as_array)
        .is_some_and(|items| {
            items.iter().any(|v| {
                v.as_object()
                    .is_some_and(|o| o.get("text").is_some_and(|t| !t.is_string()))
            })
        })
    {
        return (false, format!("{slug}: unparseable company info"));
    }
    let text = result
        .and_then(|v| v.get("content"))
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|v| v.get("text").and_then(Value::as_str))
                .collect::<String>()
        })
        .unwrap_or_default();
    if reply.get("error").is_some() || result.and_then(|v| v.get("isError")).is_some_and(truth) {
        let detail = if text.is_empty() {
            error_json(reply.get("error").unwrap_or(&Value::Null))
        } else {
            text
        };
        return (
            false,
            format!(
                "{slug}: tool error: {}",
                detail.chars().take(300).collect::<String>()
            ),
        );
    }
    let parsed = serde_json::from_str::<Value>(&text).ok();
    let Some(object) = parsed.as_ref().and_then(Value::as_object) else {
        return (false, format!("{slug}: unparseable company info"));
    };
    let name = object.get("CompanyName").unwrap_or(&Value::Null);
    if name.as_str() != Some(expect) {
        return (
            false,
            format!(
                "{slug}: WRONG COMPANY: got {}, expected {}",
                repr(name),
                repr(&json!(expect))
            ),
        );
    }
    (true, format!("{slug}: ok ({expect}, {elapsed:.1}s)"))
}
pub async fn check_company(
    client: &Client,
    slug: &str,
    port: u16,
    expect: &str,
    wait: Duration,
    verbose: bool,
) -> (bool, String) {
    let started = Instant::now();
    let mark = |step: &str| {
        if verbose {
            eprintln!(
                "  [{slug}] {step} at +{:.1}s",
                started.elapsed().as_secs_f64()
            );
        }
    };
    let result=async{
        let mut session=Session::open(client.clone(),port,slug,wait).await?;mark("sse endpoint");
        let result=async{
            session.post(json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"qbo-mcp-keepalive","version":"1"}}}),wait).await?;
            session.wait(1,wait).await?;mark("initialized");
            session.post(json!({"jsonrpc":"2.0","method":"notifications/initialized"}),wait).await?;
            session.post(json!({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_company_info","arguments":{"params":{}}}}),wait).await?;
            let reply=session.wait(2,wait).await?;mark("company info");Ok::<_,String>((reply,started.elapsed().as_secs_f64()))
        }.await;drop(session);mark("closed");result
    }.await;
    match result {
        Ok((reply, elapsed)) => company_result(slug, expect, &reply, elapsed),
        Err(error) => (false, format!("{slug}: transport failure: {error}")),
    }
}
async fn external_request(
    client: &Client,
    url: &str,
    body: Option<Value>,
    wait: Duration,
) -> Result<Response> {
    let mut url = reqwest::Url::parse(url).map_err(|_| "Invalid endpoint")?;
    let mut body = body;
    let mut visited = HashMap::new();
    for _ in 0..11 {
        let request = if let Some(value) = &body {
            client.post(url.clone()).json(value)
        } else {
            client.get(url.clone())
        };
        let response = request.timeout(wait).send().await.map_err(transport)?;
        let status = response.status().as_u16();
        if !matches!(status, 301 | 302 | 303 | 307 | 308)
            || (body.is_some() && matches!(status, 307 | 308))
        {
            return Ok(response);
        }
        let Some(location) = response
            .headers()
            .get("location")
            .and_then(|v| v.to_str().ok())
        else {
            return Ok(response);
        };
        let next = url.join(location).map_err(|_| "Invalid redirect")?;
        if !matches!(next.scheme(), "http" | "https")
            || !next.username().is_empty()
            || next.password().is_some()
        {
            return Err("Unsafe redirect refused".into());
        }
        let count = visited.entry(next.to_string()).or_insert(0);
        *count += 1;
        if *count > 4 {
            return Err("Redirect limit exceeded".into());
        }
        url = next;
        body = None;
    }
    Err("Redirect limit exceeded".into())
}
pub async fn check_gate(client: &Client, public_host: &str, slug: &str) -> (bool, String) {
    let result = external_request(
        client,
        &format!("https://{public_host}/{slug}/healthz"),
        None,
        Duration::from_secs(20),
    )
    .await;
    match result {
        Ok(response) => match response.status().as_u16() {
            401 => (true, format!("{slug}: public route gated (401)")),
            status if (200..300).contains(&status) => (
                false,
                format!("{slug}: public route answered {status} WITHOUT a bearer (gate down?)"),
            ),
            status => (false, format!("{slug}: public route HTTP {status}")),
        },
        Err(error) => (false, format!("{slug}: public route unreachable: {error}")),
    }
}
pub async fn slack(client: &Client, webhook: Option<&str>, text: &str) -> Result<()> {
    let Some(webhook) = webhook.filter(|v| !v.is_empty()) else {
        eprintln!("(no SLACK_WEBHOOK_URL; not posting)");
        return Ok(());
    };
    let response = external_request(
        client,
        webhook,
        Some(json!({"text":text})),
        Duration::from_secs(30),
    )
    .await?;
    let status = response.status().as_u16();
    if !(200..300).contains(&status) {
        return Err(format!("Slack HTTP {status}"));
    }
    let body = response.bytes().await.map_err(transport)?;
    let body = String::from_utf8_lossy(&body);
    let body = body.trim_matches(py_space);
    if body != "ok" {
        return Err(format!(
            "slack returned {status}: {}",
            body.chars().take(200).collect::<String>()
        ));
    }
    Ok(())
}
pub fn notification(ok: bool, heartbeat: bool, date: &str, report: &str) -> Option<String> {
    if !ok {
        Some(format!("*QuickBooks MCP keep-alive FAILED* ({date})\n{report}\nRe-authorize: see Systems registry entry “QuickBooks Online MCP”."))
    } else if heartbeat {
        Some(format!(
            "QuickBooks MCP keep-alive: all companies OK ({date})\n{report}"
        ))
    } else {
        None
    }
}
