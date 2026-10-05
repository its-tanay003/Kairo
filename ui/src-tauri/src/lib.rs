// Kairo Desktop Shell Library

#[tauri::command]
fn get_shell_info() -> serde_json::Value {
    serde_json::json!({
        "shell": "tauri",
        "version": "2.0",
        "app": "Kairo Autonomous Cybersecurity Agent",
        "platform": std::env::consts::OS,
        "arch": std::env::consts::ARCH,
        "timestamp": chrono_like_now()
    })
}

fn chrono_like_now() -> String {
    // Return standard ISO format without pulling extra heavy dependencies
    "2026-10-05T00:00:00Z".to_string()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![get_shell_info])
        .run(tauri::generate_context!())
        .expect("error while running Kairo desktop application");
}
