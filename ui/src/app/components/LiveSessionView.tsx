"use client";

import React, { useEffect, useState, useRef } from "react";

export interface Collaborator {
  user_id: string;
  role: string;
  client_type: string;
  joined_at?: string;
  last_active?: string;
  active_view?: string;
}

export interface SharedProject {
  project_id: string;
  name: string;
  description?: string;
  owner_id: string;
  status: string;
  active_workspace_id?: string;
  active_session_id?: string;
  collaborators: Collaborator[];
  shared_state: {
    active_target?: string;
    notes?: string;
    tags?: string[];
    live_scratchpad?: string;
    [key: string]: unknown;
  };
  created_at: string;
  updated_at: string;
  online_count?: number;
  active_presence?: Collaborator[];
}

interface LiveSessionViewProps {
  ws: WebSocket | null;
  activeProjectId: string | null;
  currentUserId: string;
  clientType: string;
  onProjectChange?: (projectId: string) => void;
}

export default function LiveSessionView({
  ws,
  activeProjectId,
  currentUserId,
  clientType,
  onProjectChange,
}: LiveSessionViewProps) {
  const [project, setProject] = useState<SharedProject | null>(null);
  const [allProjects, setAllProjects] = useState<SharedProject[]>([]);
  const [onlinePeers, setOnlinePeers] = useState<Collaborator[]>([]);
  const [scratchpadText, setScratchpadText] = useState<string>("");
  const [activeTarget, setActiveTarget] = useState<string>("target.local");
  const [isEditingTarget, setIsEditingTarget] = useState<boolean>(false);
  const [saveStatus, setSaveStatus] = useState<"synced" | "saving" | "peer_typing">("synced");
  const [recentActions, setRecentActions] = useState<Array<{ id: string; user: string; text: string; time: string; type: string }>>([]);
  const [newCollabId, setNewCollabId] = useState<string>("");
  const [newCollabRole, setNewCollabRole] = useState<string>("editor");
  const [showInviteModal, setShowInviteModal] = useState<boolean>(false);
  const [showNewProjectModal, setShowNewProjectModal] = useState<boolean>(false);
  const [newProjectName, setNewProjectName] = useState<string>("");
  const [newProjectDesc, setNewProjectDesc] = useState<string>("");
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 1. Fetch available projects
  const refreshProjectsList = () => {
    fetch("http://localhost:4000/projects")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.projects) {
          setAllProjects(data.projects);
          if (!activeProjectId && data.projects.length > 0) {
            onProjectChange?.(data.projects[0].project_id);
          }
        }
      })
      .catch((e) => console.error("Failed to fetch projects list", e));
  };

  // 2. Fetch active project details
  const fetchActiveProject = (projId: string) => {
    fetch(`http://localhost:4000/projects/${projId}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.project) {
          const p: SharedProject = data.project;
          setProject(p);
          setScratchpadText(p.shared_state?.live_scratchpad || "");
          setActiveTarget(p.shared_state?.active_target || "target.local");
          setOnlinePeers(p.active_presence || []);
        }
      })
      .catch((e) => console.error("Failed to fetch active project details", e));
  };

  useEffect(() => {
    let ignore = false;
    fetch("http://localhost:4000/projects")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!ignore && data?.projects) {
          setAllProjects(data.projects);
          if (!activeProjectId && data.projects.length > 0) {
            onProjectChange?.(data.projects[0].project_id);
          }
        }
      })
      .catch((e) => console.error("Failed to fetch projects list", e));

    return () => {
      ignore = true;
    };
  }, [activeProjectId, onProjectChange]);

  useEffect(() => {
    if (!activeProjectId) return;
    let ignore = false;
    fetch(`http://localhost:4000/projects/${activeProjectId}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!ignore && data?.project) {
          const p: SharedProject = data.project;
          setProject(p);
          setScratchpadText(p.shared_state?.live_scratchpad || "");
          setActiveTarget(p.shared_state?.active_target || "target.local");
          setOnlinePeers(p.active_presence || []);
        }
      })
      .catch((e) => console.error("Failed to fetch active project details", e));

    // Send WebSocket join_project notification
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(
        JSON.stringify({
          type: "join_project",
          projectId: activeProjectId,
          userId: currentUserId,
          role: "editor",
          activeView: "live_session",
        })
      );
    }

    return () => {
      ignore = true;
    };
  }, [activeProjectId, ws, currentUserId]);

  // 3. Listen to WebSocket events for real-time collaboration
  useEffect(() => {
    if (!ws) return;

    const handleMessage = (evt: MessageEvent) => {
      try {
        const data = JSON.parse(evt.data);

        if (data.type === "project_peer_joined") {
          if (data.projectId === activeProjectId) {
            setRecentActions((prev) => [
              {
                id: `act_${Date.now()}_${Math.random()}`,
                user: data.userId || "Peer",
                text: `joined the shared session (${data.clientType || "device"})`,
                time: new Date().toLocaleTimeString(),
                type: "join",
              },
              ...prev.slice(0, 19),
            ]);
            // Refresh presence
            if (activeProjectId) fetchActiveProject(activeProjectId);
          }
        }

        if (data.type === "project_peer_left") {
          if (data.projectId === activeProjectId) {
            setRecentActions((prev) => [
              {
                id: `act_${Date.now()}_${Math.random()}`,
                user: data.userId || "Peer",
                text: "disconnected from session",
                time: new Date().toLocaleTimeString(),
                type: "leave",
              },
              ...prev.slice(0, 19),
            ]);
            setOnlinePeers((prev) => prev.filter((p) => p.user_id !== data.userId));
          }
        }

        if (data.type === "project_state_synced") {
          if (data.projectId === activeProjectId) {
            if (data.updatedBy !== currentUserId) {
              setSaveStatus("peer_typing");
              if (data.project?.shared_state?.live_scratchpad !== undefined) {
                setScratchpadText(data.project.shared_state.live_scratchpad);
              }
              if (data.project?.shared_state?.active_target !== undefined) {
                setActiveTarget(data.project.shared_state.active_target);
              }
              setRecentActions((prev) => [
                {
                  id: `act_${Date.now()}_${Math.random()}`,
                  user: data.updatedBy || "Collaborator",
                  text: `updated project state (${(data.updatedKeys || []).join(", ")})`,
                  time: new Date().toLocaleTimeString(),
                  type: "sync",
                },
                ...prev.slice(0, 19),
              ]);
              setTimeout(() => setSaveStatus("synced"), 1000);
            }
            setProject(data.project);
          }
        }

        if (data.type === "peer_activity") {
          if (data.projectId === activeProjectId && data.userId !== currentUserId) {
            setSaveStatus("peer_typing");
            if (data.scratchpad !== undefined) {
              setScratchpadText(data.scratchpad);
            }
            setTimeout(() => setSaveStatus("synced"), 1500);
          }
        }
      } catch {
        // ignore non-json
      }
    };

    ws.addEventListener("message", handleMessage);
    return () => ws.removeEventListener("message", handleMessage);
  }, [ws, activeProjectId, currentUserId]);

  // Periodic heartbeat
  useEffect(() => {
    if (!activeProjectId) return;
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`http://localhost:4000/projects/${activeProjectId}/presence`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_id: currentUserId,
            client_type: clientType,
            role: "editor",
            active_view: "live_session",
          }),
        });
        if (res.ok) {
          const data = await res.json();
          setOnlinePeers(data.collaborators_online || []);
        }
      } catch {
        // ignore
      }
    }, 15000);
    return () => clearInterval(interval);
  }, [activeProjectId, currentUserId, clientType]);

  // 4. Handle scratchpad changes with debounce & sync
  const handleScratchpadChange = (newVal: string) => {
    setScratchpadText(newVal);
    setSaveStatus("saving");

    // Real-time broadcast to peers
    if (ws && ws.readyState === WebSocket.OPEN && activeProjectId) {
      ws.send(
        JSON.stringify({
          type: "collaborator_action",
          projectId: activeProjectId,
          userId: currentUserId,
          action: "scratchpad_edit",
          scratchpad: newVal,
        })
      );
    }

    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    saveTimeoutRef.current = setTimeout(async () => {
      if (!activeProjectId) return;
      try {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(
            JSON.stringify({
              type: "project_state_update",
              projectId: activeProjectId,
              userId: currentUserId,
              stateUpdates: { live_scratchpad: newVal },
            })
          );
        } else {
          await fetch(`http://localhost:4000/projects/${activeProjectId}/state`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              user_id: currentUserId,
              state_updates: { live_scratchpad: newVal },
            }),
          });
        }
        setSaveStatus("synced");
      } catch (err) {
        console.error("Failed to persist scratchpad", err);
      }
    }, 600);
  };

  // 5. Update Target
  const handleSaveTarget = async () => {
    if (!activeProjectId) return;
    setIsEditingTarget(false);
    try {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(
          JSON.stringify({
            type: "project_state_update",
            projectId: activeProjectId,
            userId: currentUserId,
            stateUpdates: { active_target: activeTarget },
          })
        );
      } else {
        await fetch(`http://localhost:4000/projects/${activeProjectId}/state`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_id: currentUserId,
            state_updates: { active_target: activeTarget },
          }),
        });
      }
      setRecentActions((prev) => [
        {
          id: `act_${Date.now()}`,
          user: currentUserId,
          text: `updated active assessment target to '${activeTarget}'`,
          time: new Date().toLocaleTimeString(),
          type: "target",
        },
        ...prev,
      ]);
    } catch (e) {
      console.error("Failed to update target", e);
    }
  };

  // 6. Add Collaborator
  const handleAddCollaborator = async () => {
    if (!activeProjectId || !newCollabId.trim()) return;
    try {
      const res = await fetch(`http://localhost:4000/projects/${activeProjectId}/collaborators`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: newCollabId.trim(),
          role: newCollabRole,
          client_type: "browser-desktop",
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setProject(data.project);
        setNewCollabId("");
        setShowInviteModal(false);
      }
    } catch (e) {
      console.error("Failed to add collaborator", e);
    }
  };

  // 7. Create New Project
  const handleCreateProject = async () => {
    if (!newProjectName.trim()) return;
    try {
      const res = await fetch("http://localhost:4000/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: newProjectName.trim(),
          description: newProjectDesc.trim(),
          owner_id: currentUserId,
          initial_state: {
            active_target: "target.local",
            notes: "Initial project setup.",
            live_scratchpad: `# ${newProjectName.trim()} Session Notes\n- Initialized by ${currentUserId}.\n`,
          },
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setShowNewProjectModal(false);
        setNewProjectName("");
        setNewProjectDesc("");
        await refreshProjectsList();
        onProjectChange?.(data.project.project_id);
      }
    } catch (e) {
      console.error("Failed to create project", e);
    }
  };

  const getClientIcon = (type: string) => {
    if (type?.includes("mobile")) return "📱";
    if (type?.includes("linux")) return "🐧";
    if (type?.includes("windows")) return "🪟";
    if (type?.includes("tauri")) return "⚡";
    return "💻";
  };

  return (
    <div className="live-session-container">
      {/* Top Banner: Project Switcher & Real-time Presence Bar */}
      <div className="live-session-header">
        <div className="project-selector-wrapper">
          <div className="project-title-row">
            <span className="folder-icon">📁</span>
            <select
              className="project-select"
              value={activeProjectId || ""}
              onChange={(e) => onProjectChange?.(e.target.value)}
            >
              {allProjects.map((p) => (
                <option key={p.project_id} value={p.project_id}>
                  {p.name} ({p.online_count || 1} online)
                </option>
              ))}
            </select>
            <button
              className="mini-icon-btn"
              onClick={() => setShowNewProjectModal(true)}
              title="Create New Shared Project"
            >
              ➕ New
            </button>
            <button
              className="mini-icon-btn"
              onClick={() => setShowInviteModal(true)}
              title="Invite Collaborator"
            >
              👥 Invite
            </button>
          </div>
          {project?.description && (
            <p className="project-desc-text">{project.description}</p>
          )}
        </div>

        {/* Live Collaborators Presence Strip */}
        <div className="presence-section">
          <div className="presence-label-row">
            <span className="pulse-indicator online" />
            <span className="presence-title">Live Collaborators ({onlinePeers.length || 1})</span>
          </div>
          <div className="presence-chips-row">
            {onlinePeers.map((peer) => (
              <div
                key={peer.user_id}
                className={`collab-chip ${peer.user_id === currentUserId ? "self" : ""}`}
                title={`Last active: ${peer.last_active || "now"}`}
              >
                <span className="collab-icon">{getClientIcon(peer.client_type)}</span>
                <span className="collab-name">{peer.user_id}</span>
                <span className={`collab-role-pill ${peer.role}`}>{peer.role}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Main Grid: Project State & Shared Scratchpad + Real-time Action Stream */}
      <div className="live-session-body">
        {/* Left Column: Shared Target & Synchronized Scratchpad */}
        <div className="session-main-pane">
          {/* Target & Scope Binding Bar */}
          <div className="target-binding-card">
            <div className="target-header">
              <div className="target-info">
                <span className="target-label">ACTIVE AUDIT TARGET</span>
                {isEditingTarget ? (
                  <div className="target-input-row">
                    <input
                      type="text"
                      className="target-input"
                      value={activeTarget}
                      onChange={(e) => setActiveTarget(e.target.value)}
                    />
                    <button className="target-save-btn" onClick={handleSaveTarget}>
                      Save
                    </button>
                    <button
                      className="target-cancel-btn"
                      onClick={() => setIsEditingTarget(false)}
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <div className="target-display-row">
                    <span className="target-val-text">{activeTarget}</span>
                    <button
                      className="edit-target-btn"
                      onClick={() => setIsEditingTarget(true)}
                    >
                      ✏️ Edit
                    </button>
                  </div>
                )}
              </div>
              <div className="scope-sync-badge">
                <span className="badge-dot" />
                <span>Scope Contract Bound (Task 2.3)</span>
              </div>
            </div>
            <div className="project-meta-chips">
              <span className="meta-tag">Owner: {project?.owner_id || "alice_secops"}</span>
              <span className="meta-tag">Session: {project?.active_session_id || "sess_live"}</span>
              <span className="meta-tag">Status: {project?.status?.toUpperCase() || "ACTIVE"}</span>
              <span className={`sync-status-pill ${saveStatus}`}>
                {saveStatus === "synced" && "✓ All peers synchronized"}
                {saveStatus === "saving" && "⏳ Syncing..."}
                {saveStatus === "peer_typing" && "✍️ Peer editing..."}
              </span>
            </div>
          </div>

          {/* Collaborative Scratchpad / Shared Field Notes */}
          <div className="scratchpad-card">
            <div className="scratchpad-header">
              <div className="scratchpad-title">
                <span>📝 Multi-User Live Scratchpad & Assessment Notes</span>
                <span className="scratchpad-sub">Real-time bi-directional sync across all active browsers</span>
              </div>
              <div className="scratchpad-controls">
                <button
                  className="scratchpad-tool-btn"
                  onClick={() =>
                    handleScratchpadChange(
                      scratchpadText + `\n- [${new Date().toLocaleTimeString()}] ${currentUserId}: `
                    )
                  }
                >
                  + Add Timestamp Note
                </button>
              </div>
            </div>
            <textarea
              className="scratchpad-textarea"
              placeholder="# Collaborative Assessment Notes&#10;- Record live findings, shared commands, and hypothesis here...&#10;- Changes sync immediately to all connected team members."
              value={scratchpadText}
              onChange={(e) => handleScratchpadChange(e.target.value)}
            />
          </div>
        </div>

        {/* Right Column: Live Collaboration Action Feed */}
        <div className="session-side-pane">
          <div className="action-feed-card">
            <div className="action-feed-header">
              <div className="feed-title-row">
                <span className="feed-pulse-dot" />
                <h3>Live Collaboration Feed</h3>
              </div>
              <span className="feed-count">{recentActions.length} events</span>
            </div>
            <div className="action-feed-list">
              {recentActions.length === 0 ? (
                <div className="feed-empty-state">
                  <p>No collaborator actions recorded yet.</p>
                  <p className="feed-empty-sub">
                    Edits to the scratchpad, target updates, and peer connections stream here live.
                  </p>
                </div>
              ) : (
                recentActions.map((act) => (
                  <div key={act.id} className={`feed-action-item ${act.type}`}>
                    <div className="feed-action-meta">
                      <span className="feed-user">{act.user}</span>
                      <span className="feed-time">{act.time}</span>
                    </div>
                    <div className="feed-action-text">{act.text}</div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Project Roster & Roles */}
          <div className="roster-card">
            <div className="roster-header">
              <h4>Project Roster ({project?.collaborators?.length || 1})</h4>
              <button
                className="invite-small-btn"
                onClick={() => setShowInviteModal(true)}
              >
                + Add
              </button>
            </div>
            <div className="roster-list">
              {(project?.collaborators || [
                { user_id: project?.owner_id || "alice_secops", role: "owner", client_type: "browser-desktop" },
              ]).map((c) => (
                <div key={c.user_id} className="roster-row">
                  <div className="roster-user-info">
                    <span className="user-icon">{getClientIcon(c.client_type)}</span>
                    <span className="user-id-text">{c.user_id}</span>
                  </div>
                  <span className={`roster-role-badge ${c.role}`}>{c.role}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Modal: Invite Collaborator */}
      {showInviteModal && (
        <div className="modal-backdrop">
          <div className="modal-box">
            <div className="modal-header">
              <h3>Invite Collaborator to Project</h3>
              <button className="close-btn" onClick={() => setShowInviteModal(false)}>✕</button>
            </div>
            <div className="modal-body">
              <p className="modal-info-text">
                Add a security operator or analyst to collaborate in real time on this project.
              </p>
              <div className="form-group">
                <label>User ID / Operator Handle</label>
                <input
                  type="text"
                  placeholder="e.g. bob_redteam"
                  value={newCollabId}
                  onChange={(e) => setNewCollabId(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label>Role</label>
                <select
                  value={newCollabRole}
                  onChange={(e) => setNewCollabRole(e.target.value)}
                >
                  <option value="editor">Editor (Can run tools & edit scratchpad)</option>
                  <option value="viewer">Viewer (Read-only observation)</option>
                  <option value="auditor">Auditor (Read-only + export audit logs)</option>
                </select>
              </div>
            </div>
            <div className="modal-footer">
              <button className="secondary-btn" onClick={() => setShowInviteModal(false)}>
                Cancel
              </button>
              <button className="primary-btn" onClick={handleAddCollaborator}>
                Add Collaborator
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Create New Project */}
      {showNewProjectModal && (
        <div className="modal-backdrop">
          <div className="modal-box">
            <div className="modal-header">
              <h3>Create Shared Project</h3>
              <button className="close-btn" onClick={() => setShowNewProjectModal(false)}>✕</button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label>Project Name</label>
                <input
                  type="text"
                  placeholder="e.g. Operation Chimera External Recon"
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label>Description</label>
                <textarea
                  placeholder="Describe assessment scope and team objectives..."
                  value={newProjectDesc}
                  onChange={(e) => setNewProjectDesc(e.target.value)}
                />
              </div>
            </div>
            <div className="modal-footer">
              <button className="secondary-btn" onClick={() => setShowNewProjectModal(false)}>
                Cancel
              </button>
              <button className="primary-btn" onClick={handleCreateProject}>
                Create Project
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
