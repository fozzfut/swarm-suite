# ReviewSwarm Roadmap

## Current: v0.2.3 (stable)

227 tests, 26 MCP tools, 13 experts, MCP server works, PyPI published.

---

## v0.3.0 — Polish (remaining findings from self-review)

### Logging (9 findings)
- [ ] Add proper logging to all 9 modules that currently have zero logging
- [ ] session_manager: log session create/end/expire events
- [ ] finding_store: log post/update/flush operations
- [ ] reaction_engine: log consensus state transitions
- [ ] claim_registry: log claim/release/expire events
- [ ] event_bus: log publish/subscribe/queue-full events
- [ ] message_bus: log send/route/delivery events
- [ ] orchestrator: log planning decisions
- [ ] server: log tool calls and errors
- [ ] rate_limiter: log rate limit events

### Thread Safety (5 findings)
- [ ] FindingStore.get() returns mutable refs — return copies or frozen objects
- [ ] _fan_out() iterates _subscribers without lock — snapshot before iteration
- [ ] resource_subscriptions dict mutated concurrently — add lock
- [ ] _resolve_agent_id untyped ctx parameter
- [ ] Session ID generation race under parallel process starts — use UUID fallback

### Error Handling (6 findings)
- [ ] PhaseBarrier._load() bare except:pass — add logging like other _load() methods
- [ ] PhaseBarrier._save() non-atomic write — use tempfile+replace pattern
- [ ] list_sessions() crashes on corrupt meta.json — use _load_meta() which handles it
- [ ] _prune_old_sessions() raw json.loads — use _load_meta()
- [ ] Config.load() crashes on unexpected YAML keys — ignore unknown keys
- [ ] Claim.is_expired() crashes on corrupt timestamps — try/except

### Performance (4 findings)
- [ ] _flush() full JSONL rewrite on every mutation — add dirty flag + batch flush
- [ ] find_duplicates O(N*M) word-set comparison — consider indexing by file
- [ ] ClaimRegistry flat list O(N) scans — use dict index by (session, file, expert)
- [ ] get_claims parses ISO datetime on every call — cache expiry check

### Type Safety (4 findings)
- [ ] Finding.reactions/comments as list[dict] — define ReactionDict/CommentDict TypedDict
- [ ] ReviewPlan uses list[dict] for experts/assignments/phases — define TypedDicts
- [ ] Mixed .get() vs [] access patterns — standardize
- [ ] json.loads returns used without isinstance check — add validation

### Cleanup (5 findings)
- [ ] tool_broadcast duplicates tool_send_message — remove or make thin wrapper with rate limit
- [ ] get_findings return shape changes based on caller_role — always return same shape
- [ ] get_summary default format overrides config — respect config when MCP param is empty
- [ ] Unbounded event/message lists — add max_events/max_messages config with eviction
- [ ] Rate limiter entries not cleaned on session end — add cleanup

### Documentation (3 findings)
- [ ] CI master branch reference — already removed
- [ ] CI missing macOS — already added
- [ ] py.typed missing from README architecture tree — add

---

## v0.4.0 — DocSwarm (separate package)

Multi-agent documentation generator. Separate repo: `doc-swarm`.

### Agents
- API Mapper — scan code, build public API map
- Algorithm Explainer — describe logic with examples
- Code Example Writer — generate working code examples
- Cross-Reference Builder — wikilinks, depends_on, INDEX.md
- Accuracy Verifier — verify docs match code
- Style Editor — consistent terminology and format
- Diagram Generator — Mermaid/PlantUML from code

### Shared Core
Extract `project-swarm-core` when DocSwarm is ready:
- File scanner + AST parser
- Dependency graph builder
- Import/export analyzer
- Session storage (JSONL/JSON)
- MCP transport layer

---

## v0.5.0 — FixSwarm (separate package)

Multi-agent code fixer based on ReviewSwarm reports.

### Agents
- Patch Generator — create minimal fixes for findings
- Test Writer — generate tests that verify the fix
- Regression Checker — ensure fix doesn't break existing tests
- Fix Verifier — re-run ReviewSwarm to verify finding is resolved

---

## v0.6.0 — ArchSwarm (separate package)

Multi-agent architecture brainstorming.

### Agents
- Simplicity Advocate — argues for simpler solutions
- Modularity Expert — ensures clean boundaries
- Reuse Finder — identifies duplication and abstraction opportunities
- Scalability Critic — challenges assumptions about growth
- Trade-off Mediator — synthesizes competing perspectives

### Key Difference
Unlike other tools (review/fix/docs are sequential), ArchSwarm is **conversational** — agents debate in real-time using the message bus, not just post findings.
