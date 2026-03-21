# Review Report

## Executive Summary

**132 findings** total

By severity: 21 high, 68 medium, 43 low

By status: 10 confirmed, 115 open, 7 duplicate

## Critical & High Findings

### No corrupt-line recovery in FindingStore._load() [confirmed]

- **Severity:** high | **Category:** omission
- **File:** `src/review_swarm/finding_store.py:231-242`
- **Actual:** json.loads(line) on line 240 will raise json.JSONDecodeError if any line in findings.jsonl is corrupt (truncated write, disk full, concurrent write collision). This crashes the entire FindingStore constructor, making the session permanently unloadable.
- **Expected:** Each line should be wrapped in try/except json.JSONDecodeError to skip corrupt lines and log a warning, allowing the remaining valid findings to load.
- **Source:** `src/review_swarm/finding_store.py:240`
- **Suggestion:** [fix] Wrap the json.loads + Finding.from_dict block in a try/except (json.JSONDecodeError, KeyError, ValueError) that logs a warning with the line number and continues. This preserves all valid data while recovering from corruption.
- **Confidence:** 95%


### MessageBus has no thread synchronization despite shared mutable state [confirmed]

- **Severity:** high | **Category:** bug
- **File:** `src/review_swarm/message_bus.py:12-298`
- **Actual:** MessageBus contains multiple mutable data structures (_messages, _inboxes, _agents, _read_watermarks) that are read and written by its public methods (send, get_inbox, get_pending, register_agent, etc.), but the class has no threading.Lock or any other synchronization. When multiple MCP tool handlers call into MessageBus concurrently (e.g., one agent calling send_message while another calls get_inbox), list appends, dict mutations, and set mutations can interleave, leading to lost messages, corrupted inboxes, or exceptions from concurrent dict modification.
- **Expected:** MessageBus should protect all mutable state with a threading.Lock, similar to how FindingStore and ClaimRegistry protect their state.
- **Source:** `src/review_swarm/message_bus.py:12-298`
- **Suggestion:** [fix] Add self._lock = threading.Lock() in __init__ and wrap all public methods (send, send_direct, send_broadcast, send_query, send_response, get_inbox, mark_read, get_pending, get_thread, get_all_messages, register_agent, unregister_agent) with "with self._lock:". Also import threading at the top of the file.
- **Confidence:** 95%


### Overly broad except clause silently swallows all errors in _inject_pending [confirmed]

- **Severity:** high | **Category:** omission
- **File:** `src/review_swarm/server.py:419-426`
- **Actual:** except (KeyError, Exception): pass catches ALL exceptions including programming errors (AttributeError, TypeError, etc.) and hides them. The comment says "session may not exist yet" but catches far more than KeyError.
- **Expected:** Catch only KeyError for the expected case. Log unexpected exceptions at error level so bugs in the message bus code are not silently hidden.
- **Source:** `src/review_swarm/server.py:425-426`
- **Suggestion:** [fix] Change to: except KeyError: pass  # session may not exist yet or ended. For other errors, add: except Exception: _log.exception("Unexpected error injecting pending messages for %s/%s", session_id, expert_role). Note: (KeyError, Exception) is redundant since Exception is a superclass of KeyError.
- **Confidence:** 95%


### TOCTOU race in get_finding_store (check-then-act without lock)

- **Severity:** high | **Category:** bug
- **File:** `src/review_swarm/session_manager.py:156-163`
- **Actual:** get_finding_store() does "if session_id not in self._stores" followed by assignment without holding self._lock. Two concurrent callers can both pass the check and both create new FindingStore instances; one will overwrite the other, causing the loser to operate on a stale/orphaned store and lose findings.
- **Expected:** The check-and-create must be atomic. Wrap the entire method body in "with self._lock" or use a per-session lock to prevent double-initialization.
- **Source:** `src/review_swarm/session_manager.py:156-163`
- **Suggestion:** [fix] Wrap lines 157-162 with "with self._lock:" to make the check-and-create atomic. Same pattern is needed for get_claim_registry, get_reaction_engine, get_message_bus, and get_event_bus which all share the identical bug.
- **Confidence:** 95%


### TOCTOU race in get_claim_registry, get_reaction_engine, get_message_bus, get_event_bus

- **Severity:** high | **Category:** bug
- **File:** `src/review_swarm/session_manager.py:165-196`
- **Actual:** All four lazy accessors (get_claim_registry lines 165-169, get_reaction_engine lines 171-180, get_message_bus lines 182-188, get_event_bus lines 190-196) use the same unprotected check-then-act pattern: read the dict, conditionally create, assign. None of them hold self._lock. Concurrent calls can create duplicate instances.
- **Expected:** Each lazy accessor should acquire self._lock before checking and creating the cached object, identical to the fix needed for get_finding_store.
- **Source:** `src/review_swarm/session_manager.py:165-196`
- **Suggestion:** [fix] Wrap each method body with "with self._lock:". Alternatively, use a dict.setdefault pattern or functools.cached_property if possible, but the lock approach is simplest given the existing code structure.
- **Confidence:** 95%


### Non-atomic compound operation in react() leads to inconsistent state

- **Severity:** high | **Category:** bug
- **File:** `src/review_swarm/reaction_engine.py:46-83`
- **Actual:** react() holds self._lock but calls store.get_by_id(), store.add_reaction(), store.add_related(), and store.update_status() which each independently acquire their own FindingStore._lock. Between these calls, another thread can read or modify the finding. For example, step 4 (add_reaction) and step 6 (_recompute_status via update_status) are separate lock acquisitions on the store -- a concurrent react() could interleave between them, seeing the reaction added but status not yet updated.
- **Expected:** The entire react() operation should appear atomic to observers. Either use a single lock acquisition on the store for the whole transaction, or expose a transactional API on FindingStore that performs all mutations under one lock hold.
- **Source:** `src/review_swarm/reaction_engine.py:46-83`
- **Suggestion:** [fix] Add a context-manager or transaction method to FindingStore that holds the lock for the duration. For example, expose store._lock to ReactionEngine (since they are tightly coupled), or create a store.with_lock() context manager. Then perform get_by_id, add_reaction, add_related, and update_status all within a single lock acquisition.
- **Confidence:** 90%


### No corrupt-line recovery in SessionEventBus._load()

- **Severity:** high | **Category:** omission
- **File:** `src/review_swarm/event_bus.py:106-114`
- **Actual:** json.loads(line) on line 114 will raise json.JSONDecodeError on corrupt lines in events.jsonl. This crashes the SessionEventBus constructor and propagates up to SessionManager.get_event_bus(), making the entire session's event bus unavailable.
- **Expected:** Each line should be wrapped in try/except json.JSONDecodeError to skip corrupt lines and log a warning, allowing the remaining valid events to load.
- **Source:** `src/review_swarm/event_bus.py:114`
- **Suggestion:** [fix] Wrap the json.loads + Event.from_dict call in try/except (json.JSONDecodeError, KeyError, ValueError) that logs a warning and continues to the next line.
- **Confidence:** 95%


### No corrupt-line recovery in MessageBus._load()

- **Severity:** high | **Category:** omission
- **File:** `src/review_swarm/message_bus.py:266-279`
- **Actual:** json.loads(line) on line 274 will raise json.JSONDecodeError on corrupt lines in messages.jsonl. This crashes the MessageBus constructor, making agent messaging unavailable for the session.
- **Expected:** Each line should be wrapped in try/except json.JSONDecodeError to skip corrupt lines and log a warning.
- **Source:** `src/review_swarm/message_bus.py:274`
- **Suggestion:** [fix] Wrap the json.loads + Message.from_dict call in try/except (json.JSONDecodeError, KeyError, ValueError) that logs a warning and continues. This is the same pattern needed in all three JSONL loaders.
- **Confidence:** 95%


### Potential deadlock: ReactionEngine._lock held while acquiring FindingStore._lock

- **Severity:** high | **Category:** bug
- **File:** `src/review_swarm/reaction_engine.py:46-114`
- **Actual:** react() acquires self._lock (ReactionEngine._lock) on line 46, then calls self._store.add_reaction() (line 70) and self._store.update_status() (line 114) which each acquire FindingStore._lock. If any other code path acquires these locks in the reverse order (FindingStore._lock then ReactionEngine._lock), a deadlock occurs. Currently no such reverse path exists, but the architecture is fragile -- adding any callback from FindingStore to ReactionEngine would create a deadlock.
- **Expected:** Lock ordering should be documented and enforced. Ideally, avoid holding one lock while acquiring another. The ReactionEngine could release its own lock before calling store methods, or use a single unified lock.
- **Source:** `src/review_swarm/reaction_engine.py:46-114`
- **Suggestion:** [fix] Either: (1) remove ReactionEngine._lock and rely solely on FindingStore._lock by using a transactional API, or (2) document the lock ordering invariant (ReactionEngine._lock must always be acquired before FindingStore._lock) in both files, or (3) restructure so ReactionEngine does not hold its lock while calling into the store.
- **Confidence:** 80%


### No corrupt-file recovery in ClaimRegistry._load()

- **Severity:** high | **Category:** omission
- **File:** `src/review_swarm/claim_registry.py:102-110`
- **Actual:** json.loads(text) on line 109 will raise json.JSONDecodeError if claims.json is corrupt (partial write, disk full). Unlike JSONL files where individual lines can be skipped, a corrupt JSON file loses ALL claims. No try/except is present.
- **Expected:** The json.loads call should be wrapped in try/except json.JSONDecodeError that logs a warning and either starts with an empty claims list or attempts to load from a backup.
- **Source:** `src/review_swarm/claim_registry.py:109`
- **Suggestion:** [fix] Wrap json.loads in try/except json.JSONDecodeError. On error, log the corruption, rename the corrupt file to claims.json.corrupt for forensics, and start with an empty claims list. Claims are advisory, so losing them is better than crashing.
- **Confidence:** 92%


### SessionEventBus has no thread synchronization despite shared mutable state

- **Severity:** high | **Category:** bug
- **File:** `src/review_swarm/event_bus.py:12-115`
- **Actual:** SessionEventBus has mutable _events list and _subscribers dict that are modified by publish_sync (appends to _events), subscribe (modifies _subscribers dict), unsubscribe (modifies _subscribers dict), and read by get_events. publish_sync is called from sync MCP tool handlers, and can race with get_events or subscribe/unsubscribe. For example, publish_sync appending to _events while get_events iterates over _events can cause a RuntimeError or missed events.
- **Expected:** SessionEventBus should protect _events and _subscribers with a threading.Lock for synchronous access. The asyncio.Queue usage in _fan_out is fine for async-only paths, but the sync paths (publish_sync, get_events, subscribe, unsubscribe) need thread safety.
- **Source:** `src/review_swarm/event_bus.py:12-115`
- **Suggestion:** [fix] Add self._lock = threading.Lock() in __init__. Wrap publish_sync, get_events, subscribe, unsubscribe, and event_count with "with self._lock:". The async publish method should also acquire the lock for the sync portion before calling _fan_out.
- **Confidence:** 92%


### Silent except:pass swallows expert suggestion failures

- **Severity:** high | **Category:** omission
- **File:** `src/review_swarm/session_manager.py:65-66`
- **Actual:** Exception during auto-suggest is caught with bare except:pass, no logging. Failures in suggest_experts (YAML parse errors, filesystem errors, regex errors) are completely invisible.
- **Expected:** Log the exception at warning level so operators can diagnose failures. The pass is correct for not blocking session creation, but the failure should be observable.
- **Source:** `src/review_swarm/session_manager.py:65-66`
- **Suggestion:** [fix] Replace bare pass with: _log.warning("Auto-suggest experts failed for %s: %s", project_path, exc) after adding import of get_logger and initializing _log = get_logger("session_manager").
- **Confidence:** 95%


### MCP handler default None for non-Optional Context parameter

- **Severity:** high | **Category:** bug
- **File:** `src/review_swarm/server.py:479-479`
- **Actual:** All 17 MCP tool handlers declare ctx: Context = None, but Context is not typed as Optional[Context]. At runtime the MCP framework injects a value, but the type annotation is a lie -- None is not a valid Context, and every handler immediately dereferences ctx.request_context without a None check.
- **Expected:** Declare parameter as ctx: Context | None = None and add a guard (if ctx is None: raise RuntimeError) before dereferencing, or use a sentinel default. This satisfies type checkers and produces a clear error instead of AttributeError on None.
- **Source:** `src/review_swarm/server.py:479`
- **Suggestion:** [fix] Change all MCP handler signatures to ctx: Context | None = None and add "if ctx is None: raise RuntimeError("MCP Context not injected")" as the first line. Alternatively, define _NO_CTX = object() as a sentinel and use that as the default.
- **Confidence:** 95%


### Unsafe dict key access in tool_post_findings_batch with untyped list[dict]

- **Severity:** high | **Category:** bug
- **File:** `src/review_swarm/server.py:270-302`
- **Actual:** tool_post_findings_batch accepts findings: list[dict] (untyped dicts) and accesses required keys like f["expert_role"], f["file"], f["line_start"] etc. via bracket notation without .get() or validation. KeyError is caught at line 300, but the function signature provides no schema enforcement and callers receive no type-checker help. The dict type is effectively Any.
- **Expected:** Define a TypedDict (e.g. FindingInput) with required and optional keys, then type the parameter as list[FindingInput]. This gives static type checking at call sites, prevents misspelled keys, and documents the expected shape. Alternatively, use a dataclass or Pydantic model for input validation.
- **Source:** `src/review_swarm/server.py:270-302`
- **Suggestion:** [fix] Create a TypedDict: class FindingInput(TypedDict): expert_role: str; file: str; line_start: int; ... and change the signature to findings: list[FindingInput]. The KeyError catch can remain as a runtime safety net but the type system will catch most issues statically.
- **Confidence:** 90%


### SessionManager has no logging -- session lifecycle events invisible

- **Severity:** high | **Category:** omission
- **File:** `src/review_swarm/session_manager.py:1-236`
- **Actual:** session_manager.py has no logging import or calls. Session creation, ending, expiration, pruning, and errors are completely silent. _prune_old_sessions deletes session directories with shutil.rmtree (line 229) without any log. _auto_expire_if_stale silently changes session status.
- **Expected:** Session lifecycle events (start, end, expire, prune) should be logged at info level. Session deletion should be logged at warning level. This is the core manager and its operations must be auditable.
- **Source:** `src/review_swarm/session_manager.py:1-236`
- **Suggestion:** [fix] Add from .logging_config import get_logger and _log = get_logger("session_manager"). Log: _log.info("Session started: %s for %s", session_id, project_path) in start_session(); _log.info("Session ended: %s (%d findings)", session_id, store.count()) in end_session(); _log.warning("Pruning old session: %s", sid) in _prune_old_sessions(); _log.info("Session auto-expired: %s", meta["session_id"]) in _auto_expire_if_stale().
- **Confidence:** 95%


### tool_send_message sets context AFTER message is persisted to disk -- context is lost

- **Severity:** high | **Category:** bug
- **File:** `src/review_swarm/server.py:337-371`
- **Actual:** tool_send_message calls mbus.send_direct/send_broadcast/send_query/send_response first (lines 360-366), which calls mbus.send() which calls _append_to_disk(message). Then on line 368-369, msg.context = context is set AFTER the message has already been serialized to messages.jsonl. The context dict is only in memory, never persisted.
- **Expected:** The context dict should be set on the Message object BEFORE it is sent/persisted, so that _append_to_disk serializes it to JSON. On server restart (or MessageBus reload), all context data will be missing from loaded messages.
- **Source:** `src/review_swarm/server.py:354-371`
- **Suggestion:** [fix] Restructure tool_send_message to build the Message object with context included before calling mbus.send(). Either (a) pass context through to the send_* convenience methods, (b) build the Message manually and call mbus.send() directly, or (c) add a context parameter to the send_* methods in MessageBus.
- **Confidence:** 95%


### server.py (940 lines, 17+ tool handlers) has no logging at all

- **Severity:** high | **Category:** omission
- **File:** `src/review_swarm/server.py:1-940`
- **Actual:** The entire server module -- the largest in the codebase -- has no logging import and no log calls. Tool invocations, rate limit rejections, validation errors, MCP server startup, and handler exceptions are all invisible. This module has 8 silent except:pass blocks.
- **Expected:** At minimum: log tool invocations at debug level, validation/rate-limit rejections at warning level, and unexpected exceptions at error level. Server startup should be logged at info level. This is the external-facing boundary of the application.
- **Source:** `src/review_swarm/server.py:1-940`
- **Suggestion:** [fix] Add from .logging_config import get_logger and _log = get_logger("server") at module level. Add _log.info("MCP server created with %d tools", ...) in create_mcp_server(). Add _log.debug("Tool call: %s(session=%s)", tool_name, session_id) in key tool handlers. Add _log.warning("Rate limit hit: %s", agent_key) when ValueError is raised by rate limiter.
- **Confidence:** 95%


### setup_logging() is defined but never called -- logging handlers never configured [duplicate]

- **Severity:** high | **Category:** omission
- **File:** `src/review_swarm/logging_config.py:9-25`
- **Actual:** logging_config.py defines setup_logging() which configures handlers and formatters, but no module in the codebase ever calls it. The only module that uses get_logger is expert_profiler.py. Since setup_logging is never invoked, the review_swarm logger has no handlers, so even the expert_profiler logs go nowhere (Python default is WARNING to stderr only with no formatting).
- **Expected:** setup_logging() should be called during application startup, either in cli.py serve/review commands or in create_app_context() in server.py, to ensure the logging infrastructure is actually active.
- **Source:** `src/review_swarm/logging_config.py:9-25`
- **Suggestion:** [fix] Call setup_logging() in create_app_context() in server.py and in the cli.py main() group callback. E.g., add: from .logging_config import setup_logging; setup_logging() at the top of create_app_context().
- **Confidence:** 95%


### _flush() rewrites entire JSONL file on every single-field mutation

- **Severity:** high | **Category:** performance
- **File:** `src/review_swarm/finding_store.py:200-223`
- **Actual:** update_status(), add_reaction(), add_comment(), and add_related() each call _flush(), which serializes ALL findings to JSON, writes to a temp file, and does os.replace. With N findings, every reaction/comment/status-update costs O(N) serialization + full file rewrite. In the cross-check phase where many reactions are posted, this becomes a severe I/O bottleneck.
- **Expected:** Batch mutations and flush periodically, or use a write-ahead log (append-only) for mutations with periodic compaction. Alternatively, use an indexed file format or lightweight DB (sqlite) that supports in-place updates.
- **Source:** `src/review_swarm/finding_store.py:200-223`
- **Suggestion:** [fix] Option 1 (minimal change): Buffer mutations and flush at most once per N mutations or T seconds using a dirty flag + timer. Option 2 (append-only): Write mutation records (e.g., {"op":"update_status","id":"f-xx","status":"confirmed"}) to a separate mutations.jsonl, apply on load. Option 3: Switch to sqlite for the backing store, getting atomic in-place updates for free.
- **Confidence:** 92%


### _rebuild_inboxes() is O(N^2) due to _find_message() calls inside loop

- **Severity:** high | **Category:** performance
- **File:** `src/review_swarm/message_bus.py:281-297`
- **Actual:** _rebuild_inboxes() iterates all N messages. For each RESPONSE message, it calls _find_message() which itself iterates all N messages to find the original query. With R response messages out of N total, cost is O(N + R*N) which approaches O(N^2) when many responses exist. This runs on every _load() (startup/reconnect).
- **Expected:** With a message-by-ID index (dict), _find_message becomes O(1), making _rebuild_inboxes O(N) total -- an order-of-magnitude improvement for sessions with many messages.
- **Source:** `src/review_swarm/message_bus.py:281-297`
- **Suggestion:** [fix] Build self._messages_by_id dict during _load() before calling _rebuild_inboxes(). Then _rebuild_inboxes uses O(1) lookups. Alternatively, persist inbox state to avoid full rebuild on load. For broadcast/query routing, also consider indexing agents seen during load to avoid iterating self._agents per broadcast message.
- **Confidence:** 92%


### suggest_experts reads entire project source into memory and concatenates into single string

- **Severity:** high | **Category:** performance
- **File:** `src/review_swarm/expert_profiler.py:47-104`
- **Actual:** suggest_experts() reads every source file in the project into file_contents dict (line 48-69), then _score_relevance() joins ALL file contents into a single string with all_text = chr(10).join(file_contents.values()) (line 104). For a project with 1000 files averaging 200 lines, this allocates hundreds of MB. The concatenation is repeated for EACH expert profile scored. With P profiles, total string allocation is O(P * total_source_size).
- **Expected:** Scan files incrementally: for each import/pattern signal, grep through files lazily or maintain a single pre-built set of import tokens. Avoid concatenating all source into one string. Build the combined text once if needed, not per-profile.
- **Source:** `src/review_swarm/expert_profiler.py:47-104`
- **Suggestion:** [fix] Move all_text = chr(10).join(file_contents.values()) OUTSIDE _score_relevance, compute it once in suggest_experts(), and pass it in. This alone eliminates P-1 redundant concatenations. Better still: pre-extract a set of import tokens and a searchable text index from the source files once, then score each profile against those lightweight structures instead of regex-searching the entire codebase per pattern per profile.
- **Confidence:** 90%


## Per-File Breakdown

### .github/workflows/ci.yml (2 findings)

- **[LOW]** CI workflow references non-existent 'master' branch (L5-7, open)

- **[LOW]** CI matrix lacks macOS despite README claiming macOS platform support (L13-15, open)

### README.md (4 findings)

- **[MEDIUM]** README badge and body claim 23 MCP tools, actual count is 21 (L18-18, open)

- **[MEDIUM]** MCP tools badge claims 23, actual count is 21 (L18-18, open)

- **[LOW]** Hardcoded test count '215 tests' will become stale as tests are added (L359-359, open)

- **[LOW]** Architecture tree in README omits py.typed marker file (L320-337, open)

### pyproject.toml (4 findings)

- **[MEDIUM]** click dependency has no upper-bound constraint (L24-24, open)

- **[MEDIUM]** pyyaml dependency has no upper-bound constraint (L25-25, open)

- **[LOW]** SSE transport relies on transitive uvicorn/starlette from mcp -- not declared explicitly (L23-23, open)

- **[LOW]** dev dependency mypy listed but project has ignore_missing_imports for all 3rd-party modules (L33-36, open)

### src/review_swarm/claim_registry.py (5 findings)

- **[HIGH]** No corrupt-file recovery in ClaimRegistry._load() (L102-110, open)

- **[MEDIUM]** ClaimRegistry._save() uses non-atomic write, risks data corruption (L112-116, open)

- **[MEDIUM]** ClaimRegistry module has no logging at all (L1-117, open)

- **[MEDIUM]** ClaimRegistry stores claims in flat list requiring O(N) scans for every operation (L42-98, open)

- **[MEDIUM]** ClaimRegistry._load crashes on malformed JSON with no error context (L102-110, open)

### src/review_swarm/cli.py (4 findings)

- **[LOW]** CLI module uses click.echo but no structured logging for diagnostic output (L1-457, open)

- **[LOW]** Mixed .get() and bracket access on session meta dicts in list_sessions CLI (L96-99, open)

- **[LOW]** Unused import: json in stats() function (L300-300, open)

- **[LOW]** Dead variable: total_findings assigned but never read (L345-345, open)

### src/review_swarm/config.py (2 findings)

- **[LOW]** Config validator rejects sarif as default_format but sarif is a supported report format (L86-87, open)

- **[MEDIUM]** yaml.safe_load return coerced to dict via "or {}" but _validate assumes dict (L57-57, open)

### src/review_swarm/event_bus.py (7 findings)

- **[HIGH]** No corrupt-line recovery in SessionEventBus._load() (L106-114, open)

- **[HIGH]** SessionEventBus has no thread synchronization despite shared mutable state (L12-115, open)

- **[MEDIUM]** QueueFull dropped events are silently lost (L57-60, open)

- **[MEDIUM]** _fan_out iterates _subscribers dict without synchronization while subscribe/unsubscribe can modify it (L54-60, open)

- **[LOW]** EventBus subscribe() creates queues with no automatic reclamation (L64-68, open)

- **[MEDIUM]** SessionEventBus has no logging -- event publication and I/O errors invisible (L1-115, open)

- **[MEDIUM]** Unbounded _events list grows without limit for long-running sessions (L26-94, open)

### src/review_swarm/expert_profiler.py (8 findings)

- **[MEDIUM]** ExpertProfiler._load_yaml() crashes on corrupt YAML files (L165-168, confirmed)

- **[MEDIUM]** Expert profiler reads all source files into memory with no size limit (L59-69, open)

- **[MEDIUM]** _load_yaml trusts yaml.safe_load to return dict without type check (L165-168, open)

- **[MEDIUM]** Inconsistent dict access: profile["name"] (line 87) vs profile.get("description", "") (line 88) (L84-88, open)

- **[HIGH]** suggest_experts reads entire project source into memory and concatenates into single string (L47-104, open)

- **[LOW]** Invalid regex patterns in expert profiles silently skipped (L127-131, open)

- **[LOW]** suggest_experts silently returns empty list for non-existent project path (L43-45, open)

- **[LOW]** Dead parameter: has_docs in _score_relevance() (L97-97, open)

### src/review_swarm/finding_store.py (13 findings)

- **[HIGH]** No corrupt-line recovery in FindingStore._load() (L231-242, confirmed)

- **[LOW]** Dead imports: Category and Severity imported but unused in finding_store.py (L12-12, duplicate)

- **[MEDIUM]** FindingStore._append() can leave in-memory and on-disk state inconsistent (L225-229, open)

- **[MEDIUM]** FindingStore.get() copies references but not objects, exposing mutable state (L50-93, confirmed)

- **[MEDIUM]** Temp file descriptor leak in _flush when os.fdopen fails (L210-223, open)

- **[MEDIUM]** FindingStore module has no logging -- data persistence failures invisible (L1-243, open)

- **[MEDIUM]** json.loads return used as dict without type check in _load (L240-242, open)

- **[MEDIUM]** Sequential full-list scans in get() without secondary indexes (L71-93, open)

- **[MEDIUM]** find_duplicates scans all findings with O(n*m) title word-set comparisons (L121-153, open)

- **[HIGH]** _flush() rewrites entire JSONL file on every single-field mutation (L200-223, open)

- **[MEDIUM]** JSONL _load methods across 3 modules will crash on malformed lines with no error context (L231-243, open)

- **[MEDIUM]** FindingStore._flush exception handler does cleanup but no logging before re-raise (L213-223, open)

- **[LOW]** Unused imports: Category and Severity from models (L12-12, open)

### src/review_swarm/logging_config.py (2 findings)

- **[HIGH]** setup_logging() is defined but never called -- logging handlers never configured (L9-25, duplicate)

- **[LOW]** Orphaned function: setup_logging() never called (L9-25, open)

### src/review_swarm/message_bus.py (7 findings)

- **[HIGH]** No corrupt-line recovery in MessageBus._load() (L266-279, open)

- **[HIGH]** MessageBus has no thread synchronization despite shared mutable state (L12-298, confirmed)

- **[MEDIUM]** Unhandled ValueError from MessageType(message_type) in get_inbox/get_all_messages (L146-164, open)

- **[LOW]** MessageBus inbox lists and message list grow unbounded with no eviction (L29-37, open)

- **[MEDIUM]** MessageBus has no logging -- message routing failures invisible (L1-298, open)

- **[MEDIUM]** _find_message() does linear scan over all messages instead of dict lookup (L255-259, open)

- **[HIGH]** _rebuild_inboxes() is O(N^2) due to _find_message() calls inside loop (L281-297, open)

### src/review_swarm/models.py (3 findings)

- **[MEDIUM]** Finding.reactions and Finding.comments typed as list[dict] -- untyped inner structure (L101-102, open)

- **[LOW]** Orphaned method: Reaction.generate_id() never called (L254-257, open)

- **[LOW]** Finding.from_dict uses bracket access for some keys and .get() for others without documenting which are required (L140-168, open)

### src/review_swarm/orchestrator.py (6 findings)

- **[LOW]** Dead import: now_iso imported but never used in orchestrator.py (L20-20, duplicate)

- **[LOW]** Orchestrator has no logging -- review planning decisions are not traceable (L1-378, open)

- **[MEDIUM]** ReviewPlan uses list[dict] for experts, assignments, and phases -- three different untyped shapes (L32-34, open)

- **[LOW]** Unused import: re (L13-13, open)

- **[LOW]** Unused import: field from dataclasses (L14-14, open)

- **[LOW]** Unused import: now_iso from models (L20-20, open)

### src/review_swarm/rate_limiter.py (3 findings)

- **[LOW]** RateLimiter call history grows with unique agent keys that are never pruned (L20-38, open)

- **[LOW]** RateLimiter has no logging -- rate limit events not auditable (L1-47, open)

- **[LOW]** RateLimiter.check() rebuilds entire timestamp list on every call via list comprehension (L23-38, open)

### src/review_swarm/reaction_engine.py (3 findings)

- **[HIGH]** Non-atomic compound operation in react() leads to inconsistent state (L46-83, open)

- **[HIGH]** Potential deadlock: ReactionEngine._lock held while acquiring FindingStore._lock (L46-114, open)

- **[MEDIUM]** ReactionEngine has no logging -- consensus state transitions invisible (L1-114, open)

### src/review_swarm/report_generator.py (3 findings)

- **[MEDIUM]** SARIF output hardcodes version 0.1.1, package version is 0.2.0 (L176-176, confirmed)

- **[MEDIUM]** Hardcoded version 0.1.1 in SARIF output does not match pyproject.toml version 0.2.0 (L176-176, open)

- **[LOW]** _generate_markdown iterates findings list 5+ times building redundant intermediate collections (L22-95, open)

### src/review_swarm/server.py (39 findings)

- **[MEDIUM]** Module docstring claims 17 tool handlers, actual count is 21 (L1-1, confirmed)

- **[MEDIUM]** create_mcp_server docstring claims 17 tools, actual count is 21 (L450-450, open)

- **[MEDIUM]** Overly broad except clause in _inject_pending() silently swallows bugs (L419-426, confirmed)

- **[MEDIUM]** Three layers of silent except-pass in MCP subscription handlers (L897-926, open)

- **[LOW]** Silent exception swallowing in _notify_resource_subscribers() (L430-446, open)

- **[LOW]** Dead import: Message imported but unused in server.py (L14-17, duplicate)

- **[MEDIUM]** Race in _end_session: event bus retrieved before end but used after caches cleared (L500-510, open)

- **[MEDIUM]** No validation of confidence range or line_start/line_end in tool_post_finding (L110-170, open)

- **[MEDIUM]** Batch finding errors lack index/context for identifying failed items (L270-302, open)

- **[MEDIUM]** resource_subscriptions dict mutated concurrently without synchronization (L430-446, open)

- **[MEDIUM]** Message context dict set after send() - not persisted to disk (L337-371, duplicate)

- **[MEDIUM]** TOCTOU in _react: old_status read can be stale by the time tool_react completes (L646-672, open)

- **[HIGH]** MCP handler default None for non-Optional Context parameter (L479-479, open)

- **[HIGH]** Overly broad except clause silently swallows all errors in _inject_pending (L419-426, confirmed)

- **[HIGH]** Unsafe dict key access in tool_post_findings_batch with untyped list[dict] (L270-302, open)

- **[MEDIUM]** Failed resource notifications silently swallowed and session silently discarded (L440-444, open)

- **[MEDIUM]** Three nested silent except:pass blocks hide subscription handler failures (L897-926, open)

- **[LOW]** Silent fallback to unknown agent_id hides context resolution failures (L931-939, open)

- **[MEDIUM]** _inject_pending uses overly broad except (KeyError, Exception) that swallows type errors (L419-426, open)

- **[MEDIUM]** MCP resource_subscriptions leak stale session references on session end (L499-510, open)

- **[MEDIUM]** Default value mismatch: session_name str vs None between MCP wrapper and tool function (L473-488, open)

- **[MEDIUM]** Optional Finding accessed without None check for status comparison (L648-649, open)

- **[MEDIUM]** MCP get_summary default format overrides config default_format (L675-677, open)

- **[HIGH]** tool_send_message sets context AFTER message is persisted to disk -- context is lost (L337-371, open)

- **[HIGH]** server.py (940 lines, 17+ tool handlers) has no logging at all (L1-940, open)

- **[LOW]** get_findings return type changes shape based on caller_role parameter (L609-633, open)

- **[LOW]** tool_react return type is Finding dict but function name and Reaction model suggest Reaction dict (L194-215, open)

- **[LOW]** AppContext.resource_subscriptions typed as dict[str, set] -- raw set without type parameter (L29-29, open)

- **[LOW]** end_session does not clean up rate limiter entries for the ended session (L71-72, open)

- **[LOW]** MCP claim_file wrapper does not forward agent_id parameter to callers (L536-548, open)

- **[MEDIUM]** MCP start_session converts empty string name to None but tool_start_session default is already None (L493-497, open)

- **[MEDIUM]** Redundant tool_broadcast function duplicates tool_send_message broadcast capability (L397-407, open)

- **[LOW]** MCP _post_finding double-coalesces tags and related_findings with different default semantics (L579-606, open)

- **[MEDIUM]** _resolve_agent_id parameter ctx is untyped -- implicit Any (L931-939, open)

- **[MEDIUM]** tool_get_summary docstring describes format/fmt aliasing but return type str disagrees with other tool functions returning dict (L218-229, open)

- **[LOW]** server.py docstring claims 17 tools, actual count is 21 (L1-1, duplicate)

- **[MEDIUM]** Message.context mutated after send() already persisted to disk (L368-369, duplicate)

- **[LOW]** Unused import: Path from pathlib (L6-6, open)

- **[LOW]** Unused import: Message from models (L16-16, open)

### src/review_swarm/session_manager.py (17 findings)

- **[HIGH]** TOCTOU race in get_finding_store (check-then-act without lock) (L156-163, open)

- **[HIGH]** TOCTOU race in get_claim_registry, get_reaction_engine, get_message_bus, get_event_bus (L165-196, open)

- **[MEDIUM]** No error handling in SessionManager._load_meta() (L209-210, confirmed)

- **[MEDIUM]** get_session() reads multiple stores without lock, can return inconsistent snapshot (L108-119, open)

- **[LOW]** Silent except-pass when auto-suggesting experts hides profiler errors (L59-66, open)

- **[MEDIUM]** list_sessions() iterates filesystem and writes meta.json without any lock (L121-136, open)

- **[MEDIUM]** list_sessions() crashes on any corrupt meta.json file (L121-136, open)

- **[MEDIUM]** _prune_old_sessions() crashes if shutil.rmtree fails on locked files (L212-235, confirmed)

- **[HIGH]** Silent except:pass swallows expert suggestion failures (L65-66, open)

- **[MEDIUM]** end_session holds self._lock while calling get_finding_store which may do I/O (L73-106, open)

- **[MEDIUM]** Session ID generation can produce duplicates under filesystem race (L33-35, open)

- **[MEDIUM]** EventBus subscriber queues not cleaned up on session end (L73-106, open)

- **[HIGH]** SessionManager has no logging -- session lifecycle events invisible (L1-236, open)

- **[MEDIUM]** Absolute project paths stored in meta.json may leak into logs when logging is added (L40-50, open)

- **[MEDIUM]** _load_meta returns bare dict from json.loads -- no schema validation or TypedDict (L209-210, open)

- **[MEDIUM]** _prune_old_sessions re-lists directory on every loop iteration causing O(S^2) I/O (L212-235, open)

- **[MEDIUM]** get_project_path uses meta["project_path"] without .get() or key validation (L198-201, open)

## Expert Coverage

- **api-signatures**: 1 files reviewed

- **consistency**: 6 files reviewed

- **dead-code**: 7 files reviewed

- **dependency-drift**: 2 files reviewed

- **error-handling**: 7 files reviewed

- **logging-patterns**: 12 files reviewed

- **performance**: 8 files reviewed

- **project-context**: 3 files reviewed

- **resource-lifecycle**: 7 files reviewed

- **threading-safety**: 7 files reviewed

- **type-safety**: 8 files reviewed
