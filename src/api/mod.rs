use axum::{
    extract::{Query, State},
    http::{HeaderMap, StatusCode},
    response::{Html, IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use serde::Deserialize;
use serde_json::json;
use std::net::SocketAddr;
use std::sync::Arc;
use tracing::info;

use crate::commands::AppState;

#[derive(Deserialize)]
pub struct MetricsQuery {
    pub token: Option<String>,
}

#[derive(Deserialize)]
pub struct AdminAction {
    pub action: String,
    pub chat_id: Option<i64>,
    pub message: Option<String>,
}

pub fn create_router(state: Arc<AppState>) -> Router {
    Router::new()
        .route("/", get(health_check))
        .route("/health", get(health_check))
        .route("/metrics", get(get_metrics))
        .route("/metrics/prometheus", get(get_prometheus_metrics))
        .route("/admin/", get(admin_dashboard))
        .route("/admin/api/stats", get(admin_stats))
        .route("/admin/api/queues", get(admin_queues))
        .route("/admin/api/action", post(admin_action))
        .with_state(state)
}

async fn health_check() -> &'static str {
    "OK"
}

async fn get_metrics(
    State(state): State<Arc<AppState>>,
    Query(query): Query<MetricsQuery>,
    headers: HeaderMap,
) -> Response {
    if !state.config.metrics_http_enabled {
        return (StatusCode::NOT_FOUND, "Metrics endpoint disabled").into_response();
    }

    if let Some(expected_token) = &state.config.metrics_http_token {
        let auth_header = headers
            .get("Authorization")
            .and_then(|h| h.to_str().ok())
            .and_then(|h| h.strip_prefix("Bearer "));

        let query_token = query.token.as_deref();

        if auth_header != Some(expected_token) && query_token != Some(expected_token) {
            return (StatusCode::UNAUTHORIZED, "Unauthorized").into_response();
        }
    }

    let payload = json!({
        "timestamp": chrono::Utc::now().to_rfc3339(),
        "uptime_seconds": 3600.0,
        "active_vcs": state.queues.active_chats().len(),
        "status": "healthy"
    });

    Json(payload).into_response()
}

async fn get_prometheus_metrics(State(state): State<Arc<AppState>>) -> Response {
    if !state.config.metrics_prometheus_enabled {
        return (StatusCode::NOT_FOUND, "Prometheus metrics disabled").into_response();
    }

    let active_chats = state.queues.active_chats().len();
    let body = format!(
        "# HELP musicbot_active_voice_chats Number of active voice chats\n\
         # TYPE musicbot_active_voice_chats gauge\n\
         musicbot_active_voice_chats {}\n\
         musicbot_uptime_seconds 3600\n",
        active_chats
    );

    (StatusCode::OK, [("content-type", "text/plain")], body).into_response()
}

fn check_admin_auth(headers: &HeaderMap, expected_password: &Option<String>) -> bool {
    let pass = match expected_password {
        Some(p) if !p.is_empty() => p,
        _ => return false,
    };

    if let Some(auth) = headers.get("Authorization").and_then(|h| h.to_str().ok()) {
        if let Some(encoded) = auth.strip_prefix("Basic ") {
            if let Ok(decoded) = base64::Engine::decode(&base64::engine::general_purpose::STANDARD, encoded) {
                if let Ok(credentials) = String::from_utf8(decoded) {
                    let parts: Vec<&str> = credentials.splitn(2, ':').collect();
                    if parts.len() == 2 && parts[0] == "admin" && parts[1] == pass {
                        return true;
                    }
                }
            }
        }
    }
    false
}

async fn admin_dashboard(State(state): State<Arc<AppState>>, headers: HeaderMap) -> Response {
    if state.config.admin_password.is_none() {
        return (StatusCode::SERVICE_UNAVAILABLE, "Admin panel disabled").into_response();
    }

    if !check_admin_auth(&headers, &state.config.admin_password) {
        return (
            StatusCode::UNAUTHORIZED,
            [("WWW-Authenticate", "Basic realm=\"Brook Music Bot Admin\"")],
            "Unauthorized",
        )
            .into_response();
    }

    let html = "<html><head><title>Brook Music Bot Admin</title></head><body><h1>☠️ Brook Music Bot Rust Dashboard</h1><p>Status: Active</p></body></html>";
    Html(html).into_response()
}

async fn admin_stats(State(state): State<Arc<AppState>>, headers: HeaderMap) -> Response {
    if !check_admin_auth(&headers, &state.config.admin_password) {
        return (StatusCode::UNAUTHORIZED, "Unauthorized").into_response();
    }

    let payload = json!({
        "uptime": 3600,
        "memory_percent": 15.4,
        "cpu_percent": 2.1,
        "active_vcs": state.queues.active_chats().len(),
        "engine": "Rust (Tokio / Axum / Teloxide)",
        "music_microservice": {
            "configured": state.config.music_microservice_url.is_some(),
            "healthy": state.music_backend.check_health().await
        }
    });

    Json(payload).into_response()
}

async fn admin_queues(State(state): State<Arc<AppState>>, headers: HeaderMap) -> Response {
    if !check_admin_auth(&headers, &state.config.admin_password) {
        return (StatusCode::UNAUTHORIZED, "Unauthorized").into_response();
    }

    let active_chats = state.queues.active_chats();
    let mut map = serde_json::Map::new();

    for chat_id in active_chats {
        let lock = state.queues.get_or_create(chat_id).await;
        let q = lock.read().await;
        map.insert(
            chat_id.to_string(),
            json!({
                "current": q.current,
                "queue_len": q.queue.len(),
                "loop_mode": q.loop_mode,
                "is_paused": q.is_paused,
            }),
        );
    }

    Json(json!(map)).into_response()
}

async fn admin_action(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(payload): Json<AdminAction>,
) -> Response {
    if !check_admin_auth(&headers, &state.config.admin_password) {
        return (StatusCode::UNAUTHORIZED, "Unauthorized").into_response();
    }

    match payload.action.as_str() {
        "clear_caches" => {
            state.cache.clear_all().await;
            Json(json!({"status": "caches cleared"})).into_response()
        }
        "leave_vc" => {
            if let Some(chat_id) = payload.chat_id {
                state.queues.remove_chat(chat_id).await;
                Json(json!({"status": "left_vc", "chat_id": chat_id})).into_response()
            } else {
                (StatusCode::BAD_REQUEST, Json(json!({"detail": "Missing chat_id"}))).into_response()
            }
        }
        _ => (StatusCode::BAD_REQUEST, Json(json!({"detail": "Invalid action"}))).into_response(),
    }
}

pub async fn start_api_server(port: u16, state: Arc<AppState>) {
    let app = create_router(state);
    let addr = SocketAddr::from(([0, 0, 0, 0], port));
    info!("Axum HTTP API server starting on http://{}", addr);

    if let Ok(listener) = tokio::net::TcpListener::bind(addr).await {
        axum::serve(listener, app).await.ok();
    }
}
