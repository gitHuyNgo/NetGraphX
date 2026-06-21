# NetGraphX

**Network Intelligence Dashboard** for Viettel Labs — built on NetBox, Neo4j, NetworkX, and OpenAI.

---

## Features

| Feature | Description |
|---|---|
| 🔔 Debounced Webhooks | Receives NetBox change signals but only re-syncs after configurable idle timeout OR manual "Done" click |
| 🗺️ Hierarchical Graph | Layered vis.js layout: Core → Distribution → Access → Endpoints, with pod grouping |
| 🤖 RAG Chatbot | Query your network topology in natural language |
| 🔐 RBAC | Admin (full control) and Engineer (read-only graph + chatbot) roles |

---

## Quick Start (Windows)

### 1. Install dependencies
```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment
```bat
copy .env.example .env
# Edit .env with your NetBox URL, token, Neo4j creds, OpenAI key, etc.
```

### 3. Configure users
Edit `config/users.yaml` to set your usernames and passwords.

To generate a SHA-256 password hash:
```bat
python -c "import hashlib; print(hashlib.sha256('yourpassword'.encode()).hexdigest())"
```

Default credentials (change before production!):
- `admin` / `admin123`
- `engineer` / `engineer123`

### 4. Run initial sync
```bat
python -m src.main
```

### 5. Start all services
```bat
start.bat
```
This opens two terminal windows:
- **Webhook server**: `http://localhost:5001`
- **Dashboard**: `http://localhost:8501`

Or start them separately:
```bat
# Terminal 1 — Webhook server
python -m src.webhook.server

# Terminal 2 — Streamlit dashboard
streamlit run app.py
```

---

## Webhook Configuration (NetBox side)

In NetBox → **Operations → Webhooks → Add**:

| Field | Value |
|---|---|
| Name | NetGraphX Topology Change |
| URL | `http://<your-server-ip>:5001/webhook/netbox` |
| HTTP Method | POST |
| Content Type | `application/json` |
| Additional Headers | `X-NetBox-Key: <your WEBHOOK_SECRET from .env>` |
| Events | ✅ Creations, ✅ Updates, ✅ Deletions |
| Object Types | `dcim.device`, `dcim.cable`, `dcim.interface` |

---

## RBAC Roles

| Capability | Admin | Engineer |
|---|---|---|
| View topology graph | ✅ | ✅ |
| Use RAG chatbot | ✅ | ✅ |
| See webhook status | ✅ | ✅ |
| Click "Done — Sync Now" | ✅ | ❌ |
| Edit audit rules | ✅ | ❌ |
| View registered users | ✅ | ❌ |

---

## Environment Variables

```env
# NetBox
NETBOX_URL=http://localhost:8000
NETBOX_API_TOKEN=your_token

# Neo4j
NEO4J_ENABLED=false
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password

# OpenAI / RAG
OPENAI_API_KEY=your_key
OPENAI_MODEL=gpt-4o-mini

# Webhook (debounce)
WEBHOOK_SECRET=your_secret
WEBHOOK_PORT=5001
WEBHOOK_DEBOUNCE_MINUTES=10    # Minutes of inactivity before auto-sync

# Auth
USERS_FILE=config/users.yaml
SESSION_SECRET=long-random-string
```

---

## Graph Hierarchy Levels

| Level | Layer | Device Roles |
|---|---|---|
| L0 | Core / Spine | `core`, `backbone`, `spine`, `wan router` |
| L1 | Distribution | `distribution`, `aggregation`, `collapsed-core` |
| L2 | Access / Edge | `access`, `edge`, `leaf`, `tor` |
| L3 | Endpoints | `server`, `host`, `ap`, `oob`, `management` |

Devices with unrecognized roles default to **L2 (Access)**.
