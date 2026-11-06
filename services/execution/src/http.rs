use std::sync::Arc;

use axum::{
    extract::{Path, Request, State},
    http::StatusCode,
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use uuid::Uuid;

use crate::service::{NewOrder, Service, ServiceError};

#[derive(Clone)]
pub struct AppState {
    pub svc: Arc<Service>,
    pub arena_key: Arc<String>,
}

impl IntoResponse for ServiceError {
    fn into_response(self) -> Response {
        let (code, msg) = match self {
            ServiceError::BadRequest(m) => (StatusCode::BAD_REQUEST, m),
            ServiceError::Internal(m) => (StatusCode::INTERNAL_SERVER_ERROR, m),
        };
        (code, Json(serde_json::json!({ "error": msg }))).into_response()
    }
}

async fn require_key(State(st): State<AppState>, req: Request, next: Next) -> Response {
    let ok = req
        .headers()
        .get("x-arena-key")
        .and_then(|v| v.to_str().ok())
        == Some(st.arena_key.as_str());
    if ok {
        next.run(req).await
    } else {
        (
            StatusCode::UNAUTHORIZED,
            Json(serde_json::json!({ "error": "missing or bad X-Arena-Key" })),
        )
            .into_response()
    }
}

async fn post_order(
    State(st): State<AppState>,
    Json(body): Json<NewOrder>,
) -> Result<Response, ServiceError> {
    // Run the order on its own task. When the caller's timeout fires and it hangs up, axum drops this handler;
    // without the spawn that would cancel the order halfway through the broker call and strand the fill.
    let svc = st.svc.clone();
    let rec = tokio::spawn(async move { svc.place(body).await })
        .await
        .map_err(|e| ServiceError::Internal(format!("order task failed: {e}")))??;
    Ok(Json(rec).into_response())
}

async fn get_order(
    State(st): State<AppState>,
    Path(id): Path<Uuid>,
) -> Result<Response, ServiceError> {
    Ok(match st.svc.get_order(id).await? {
        Some(o) => Json(o).into_response(),
        None => (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({ "error": "not found" })),
        )
            .into_response(),
    })
}

async fn metrics(State(st): State<AppState>) -> Result<String, ServiceError> {
    st.svc.metrics_text().await
}

pub fn router(state: AppState) -> Router {
    let authed = Router::new()
        .route("/v1/orders", post(post_order))
        .route("/v1/orders/:id", get(get_order))
        .route_layer(middleware::from_fn_with_state(state.clone(), require_key));
    Router::new()
        .route("/healthz", get(|| async { "ok" }))
        .route("/metrics", get(metrics))
        .merge(authed)
        .with_state(state)
}
