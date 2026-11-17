# -*- coding: utf-8 -*-
"""Queue the MiniMax H3 FL2V 8GB-VRAM workflow via ComfyUI API and wait for the video.

Converts the UI-format workflow JSON into API format using the live server's
/object_info definitions (widget values are mapped positionally, exactly how the
ComfyUI frontend serializes them). Supports overrides for steps/seed/prompt/etc.
"""
import json
from pathlib import Path
import sys
import time
import urllib.request
import urllib.error

SERVER = "http://127.0.0.1:8193"
WORKFLOW = str(Path(__file__).resolve().parents[1] / "workflows/MiniMax_H3_FL2VA_audio.json")

WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO", "COMFY_DYNAMICCOMBO_V3"}


def _is_widget_input(t):
    """object_info type spec: ['INT', {...}] or [['opt1','opt2'], {...}] for COMBO."""
    if not (isinstance(t, (list, tuple)) and t):
        return False
    t0 = t[0]
    return (isinstance(t0, str) and t0 in WIDGET_TYPES) or isinstance(t0, list)


def http_get_json(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def http_post_json(url, payload, timeout=60):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise SystemExit(f"POST {url} failed: HTTP {e.code}\n{body}")


def build_api_prompt(overrides):
    wf = json.load(open(WORKFLOW, encoding="utf-8"))
    obj = http_get_json(SERVER + "/object_info", timeout=120)

    links = {}
    for lk in wf.get("links", []):
        # [link_id, src_node, src_slot, dst_node, dst_slot, type]
        links[lk[0]] = (str(lk[1]), lk[2])

    prompt = {}
    for node in wf["nodes"]:
        ntype = node["type"]
        if ntype not in obj:
            raise SystemExit(f"Server does not know node type: {ntype}")
        spec = obj[ntype]["input"]
        ordered = list(spec.get("required", {}).items()) + list(spec.get("optional", {}).items())

        # widget-input names in definition order
        widget_names = [name for name, t in ordered if _is_widget_input(t)]
        wvals = node.get("widgets_values", [])
        if isinstance(wvals, dict):
            wvals = list(wvals.values())
        if len(wvals) > len(widget_names):  # e.g. LoadImage's fake upload widget
            wvals = wvals[:len(widget_names)]

        inputs = {}
        for name, val in zip(widget_names, wvals):
            inputs[name] = val

        # connection inputs from the UI graph
        for inp in node.get("inputs", []):
            if inp.get("widget") is not None:
                continue  # widget-converted input, already covered by widgets_values
            lk = inp.get("link")
            if lk is None:
                continue  # unconnected optional input (e.g. CreateVideo.audio)
            src, slot = links[lk]
            inputs[inp["name"]] = [src, slot]

        prompt[str(node["id"])] = {"class_type": ntype, "inputs": inputs}

    # apply overrides: "11.steps" style or global names
    for key, val in overrides.items():
        nid, _, field = key.partition(".")
        if nid in prompt and field:
            prompt[nid]["inputs"][field] = val
        else:
            matched = False
            for p in prompt.values():
                if key in p["inputs"]:
                    p["inputs"][key] = val
                    matched = True
                    break
            if not matched:
                raise SystemExit(f"Override target not found: {key}")

    return prompt


def main():
    overrides = {}
    args = sys.argv[1:]
    global WORKFLOW
    i = 0
    while i < len(args):
        if args[i] == "--workflow" and i + 1 <= len(args) - 1:
            WORKFLOW = args[i + 1]
            i += 2
        elif args[i] == "--set" and i + 2 <= len(args) - 1:
            k, v = args[i + 1], args[i + 2]
            # typed parsing
            if v.lower() in ("true", "false"):
                overrides[k] = v.lower() == "true"
            else:
                try:
                    overrides[k] = int(v)
                except ValueError:
                    try:
                        overrides[k] = float(v)
                    except ValueError:
                        overrides[k] = v
            i += 3
        else:
            raise SystemExit(f"Usage: queue_run.py [--workflow <json>] --set <key> <value> ... (got: {args})")

    prompt = build_api_prompt(overrides)
    resp = http_post_json(SERVER + "/prompt", {"prompt": prompt, "client_id": "zcode-run"})
    pid = resp.get("prompt_id")
    if not pid:
        raise SystemExit(f"No prompt_id in response: {json.dumps(resp)[:2000]}")
    print(f"queued prompt_id={pid} overrides={overrides}", flush=True)

    t0 = time.time()
    while True:
        time.sleep(10)
        try:
            hist = http_get_json(f"{SERVER}/history/{pid}")
        except urllib.error.HTTPError:
            hist = {}
        if pid in hist:
            entry = hist[pid]
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                msgs = [m for m in status.get("messages", []) if m[0] in ("execution_error", "execution_interrupted")]
                raise SystemExit("EXECUTION ERROR:\n" + json.dumps(msgs, indent=2, ensure_ascii=False)[:6000])
            if status.get("completed"):
                outs = []
                for node_out in entry.get("outputs", {}).values():
                    for kind, items in node_out.items():
                        if isinstance(items, list):
                            for it in items:
                                if isinstance(it, dict) and "filename" in it:
                                    outs.append(f"{it.get('subfolder','')}/{it['filename']}")
                print(f"DONE in {(time.time()-t0)/60:.1f} min. Outputs: {outs}", flush=True)
                return
        elapsed = (time.time() - t0) / 60
        print(f"waiting... {elapsed:.1f} min", flush=True)
        if elapsed > 180:
            raise SystemExit("Timed out after 180 min")


if __name__ == "__main__":
    main()
