"""Smoke validation for Layer A activation (run: docker exec autonomous-agent-backend python /workspace/backend/scripts/validate_layer_a_activation.py)."""

from __future__ import annotations

import json
import sys
import uuid

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
ADMIN_EMAIL = "admin@admin.com"
ADMIN_PASSWORD = "admin"


def login(client: httpx.Client) -> str:
    r = client.post(f"{BASE}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    r.raise_for_status()
    return r.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def main() -> int:
    results: list[tuple[str, bool, str]] = []
    client = httpx.Client(timeout=30.0)

    try:
        token = login(client)
        h = auth_headers(token)

        agents = client.get(f"{BASE}/agents/", headers=h).json()
        system_active = next(
            (a for a in agents if a.get("is_system") and a.get("mode") == "ACTIVE"),
            None,
        )
        if not system_active:
            results.append(("Agente sistema ACTIVE", False, "não encontrado"))
        else:
            r = client.get(
                f"{BASE}/agents/{system_active['id']}/channel-settings/whatsapp",
                headers=h,
            )
            ok = r.status_code == 200
            body = r.json()
            editable = body.get("editable") is False
            has_defaults = body.get("params", {}).get("chats_simultaneos") == 5
            results.append(
                (
                    "GET channel-settings agente is_system",
                    ok and editable and has_defaults,
                    f"status={r.status_code} editable={body.get('editable')}",
                )
            )

            r_put = client.put(
                f"{BASE}/agents/{system_active['id']}/channel-settings/whatsapp",
                headers=h,
                json={"params": {"chats_simultaneos": 99}},
            )
            results.append(
                (
                    "PUT channel-settings agente is_system → 403",
                    r_put.status_code == 403,
                    f"status={r_put.status_code}",
                )
            )

        custom_name = f"Teste Ativo {uuid.uuid4().hex[:8]}"
        r_create = client.post(
            f"{BASE}/agents/",
            headers=h,
            json={
                "name": custom_name,
                "mode": "ACTIVE",
                "description": "validação camada A",
                "config": {},
            },
        )
        custom_agent = r_create.json() if r_create.status_code == 201 else None
        if custom_agent:
            r_put2 = client.put(
                f"{BASE}/agents/{custom_agent['id']}/channel-settings/whatsapp",
                headers=h,
                json={
                    "params": {
                        "chats_simultaneos": 7,
                        "campanhas_simultaneas": 1,
                        "tentativas_sem_resposta": 2,
                        "minutos_segunda_mensagem": 20,
                        "horario_inicio": "09:00",
                        "horario_fim": "20:00",
                    }
                },
            )
            r_get2 = client.get(
                f"{BASE}/agents/{custom_agent['id']}/channel-settings/whatsapp",
                headers=h,
            )
            saved = r_get2.json().get("params", {}).get("chats_simultaneos") == 7
            results.append(
                (
                    "PUT/GET channel-settings agente custom",
                    r_put2.status_code == 200 and saved,
                    f"put={r_put2.status_code} chats={r_get2.json().get('params', {}).get('chats_simultaneos')}",
                )
            )

            camp = client.post(
                f"{BASE}/campaigns/",
                headers=h,
                json={
                    "name": f"Camp A {uuid.uuid4().hex[:6]}",
                    "agent_id": custom_agent["id"],
                    "channel_types": ["whatsapp", "voice"],
                },
            )
            if camp.status_code == 201:
                campaign = camp.json()
                r_start = client.post(
                    f"{BASE}/campaigns/{campaign['id']}/activations/whatsapp/start",
                    headers=h,
                )
                results.append(
                    (
                        "POST activations/whatsapp/start",
                        r_start.status_code == 200
                        and r_start.json().get("activation", {}).get("is_running") is True,
                        json.dumps(r_start.json())[:200],
                    )
                )
                r_act = client.get(
                    f"{BASE}/campaigns/{campaign['id']}/activations",
                    headers=h,
                )
                wa_running = any(
                    a["channel_type"] == "whatsapp" and a["is_running"]
                    for a in r_act.json().get("activations", [])
                )
                results.append(
                    ("GET activations whatsapp is_running", wa_running, str(r_act.json())[:120])
                )

                r_stop = client.post(
                    f"{BASE}/campaigns/{campaign['id']}/activations/whatsapp/stop",
                    headers=h,
                )
                stopped = (
                    r_stop.status_code == 200
                    and r_stop.json().get("is_running") is False
                )
                results.append(("POST activations/whatsapp/stop", stopped, str(r_stop.json())[:120]))

                client.delete(f"{BASE}/campaigns/{campaign['id']}", headers=h)
            client.delete(f"{BASE}/agents/{custom_agent['id']}", headers=h)

        system_campaign = next((c for c in client.get(f"{BASE}/campaigns/", headers=h).json() if c.get("is_system")), None)
        if system_campaign:
            r_sys = client.post(
                f"{BASE}/campaigns/{system_campaign['id']}/activations/whatsapp/start",
                headers=h,
            )
            results.append(
                (
                    "Campanha is_system start canal → 403",
                    r_sys.status_code == 403,
                    f"status={r_sys.status_code}",
                )
            )

        print("\n=== Validação Camada A ===\n")
        all_ok = True
        for name, ok, detail in results:
            mark = "OK" if ok else "FALHA"
            if not ok:
                all_ok = False
            print(f"[{mark}] {name}")
            print(f"       {detail}\n")
        return 0 if all_ok else 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
