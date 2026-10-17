# head/

**Not part of the running build.** An MCP tool server for the Petoi AI Head's agent (an exploration of 2026-10-11). The plan, findings and what adopting the head would take: [`../../docs/planned/ai-head/README.md`](../../docs/planned/ai-head/README.md).

`mcp_tools.py` connects *out* to the head agent's MCP access point (a secret websocket address read from `XIAOZHI_MCP_ENDPOINT` in `.env`) and answers the cloud model's `initialize`, `tools/list` and `tools/call` requests, so the model can call tools while someone talks to the head.

```bash
python -m pi_pipeline.head       # connect and serve until Ctrl-C
```

Rules the module keeps:
- The address holds a token: it is read only from the environment and never logged, printed or put in an error.
- Tools take fixed, validated arguments and return plain text. Nothing here runs a command, evaluates text as code, moves G2 or opens the serial link.
- A tool result travels through XiaoZhi's cloud, so it may only contain things that are fine to leave the house, and the vendor limits a result to about 1024 bytes (cut at 1000).
- One connection per access point: run a single connector.
- `ToolServer.handle()` is pure (a message in, a reply or nothing out), so the protocol is tested without a network.
