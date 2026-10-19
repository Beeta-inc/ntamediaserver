#!/usr/bin/env python3
"""
HyperData Sovereign Database Engine for Mobile Datacenters
Zero-dependency, multi-tenant, dual-tier (RAM L1 + SQLite WAL L2) storage
with real-time SSE pub/sub event broadcasting.
"""

import os
import re
import time
import json
import sqlite3
import hashlib
import queue
import threading
from typing import Dict, Any, List, Optional, Tuple

class HyperDataPubSub:
    """Thread-safe in-memory pub/sub event broker for real-time SSE streams."""
    def __init__(self):
        self._lock = threading.Lock()
        # Map: (tenant_id, table_name) -> set of queue.Queue
        self._subscribers: Dict[Tuple[str, str], set] = {}

    def subscribe(self, tenant_id: str, table: str = "*") -> queue.Queue:
        q = queue.Queue(maxsize=1000)
        key = (tenant_id, table)
        with self._lock:
            if key not in self._subscribers:
                self._subscribers[key] = set()
            self._subscribers[key].add(q)
        return q

    def unsubscribe(self, tenant_id: str, table: str, q: queue.Queue):
        key = (tenant_id, table)
        with self._lock:
            if key in self._subscribers:
                self._subscribers[key].discard(q)
                if not self._subscribers[key]:
                    del self._subscribers[key]

    def publish(self, tenant_id: str, table: str, event: dict):
        targets = []
        with self._lock:
            # Table-specific subscribers
            t_subs = self._subscribers.get((tenant_id, table))
            if t_subs:
                targets.extend(list(t_subs))
            # Wildcard subscribers for this tenant
            all_subs = self._subscribers.get((tenant_id, "*"))
            if all_subs:
                targets.extend(list(all_subs))

        for q in targets:
            try:
                q.put_nowait(event)
            except (queue.Full, Exception):
                pass


class HyperDataEngine:
    """
    Sovereign Dual-Tier Database Engine:
    - Tier 1: In-memory RAM Cache with TTL & reactive table version invalidation
    - Tier 2: Isolated SQLite WAL per tenant/project with auto-schema evolution
    - PubSub: Real-time event broadcasting for instant SSE streams
    """

    def __init__(self, base_storage_dir: Optional[str] = None):
        # Resolve writable base directory
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            base_storage_dir,
            os.environ.get("NETUARK_STORAGE_DIR"),
            "/sdcard/Download/NetuarkMedia",
            os.path.join(repo_dir, "data"),
            "/tmp/NetuarkMedia"
        ]
        resolved_dir = None
        for candidate in candidates:
            if not candidate:
                continue
            try:
                os.makedirs(candidate, exist_ok=True)
                test_file = os.path.join(candidate, f".hd_write_test_{os.getpid()}")
                with open(test_file, "w") as f:
                    f.write("ok")
                os.remove(test_file)
                resolved_dir = candidate
                break
            except Exception:
                continue

        if not resolved_dir:
            resolved_dir = "/tmp/NetuarkMedia"
            os.makedirs(resolved_dir, exist_ok=True)

        self.base_dir = resolved_dir
        self.projects_dir = os.path.join(self.base_dir, "projects")
        os.makedirs(self.projects_dir, exist_ok=True)

        # Thread synchronization
        self._mutex = threading.Lock()
        self._project_locks: Dict[str, threading.RLock] = {}
        
        # L1 Memory Cache: key -> (doc_dict, expire_timestamp_or_None)
        self._cache: Dict[str, Tuple[dict, Optional[float]]] = {}
        
        # Table version counters: tenant:table -> int (for query cache invalidation)
        self._table_versions: Dict[str, int] = {}
        
        # Query Cache: tenant:table:ver:query_hash -> (res_dict, expire_timestamp)
        self._query_cache: Dict[str, Tuple[dict, float]] = {}

        # PubSub Bus
        self.pubsub = HyperDataPubSub()

    def _get_project_lock(self, tenant_id: str) -> threading.RLock:
        with self._mutex:
            if tenant_id not in self._project_locks:
                self._project_locks[tenant_id] = threading.RLock()
            return self._project_locks[tenant_id]

    def _clean_tenant(self, tenant_id: Optional[str]) -> str:
        safe = re.sub(r'[^a-zA-Z0-9_\-]', '', str(tenant_id or "public_guest")).strip()
        return safe if safe else "public_guest"

    def _clean_table(self, table_name: Optional[str]) -> str:
        safe = re.sub(r'[^a-zA-Z0-9_]', '', str(table_name or "records")).strip()
        return safe if safe else "records"

    def get_project_db_path(self, tenant_id: str) -> str:
        safe_tenant = self._clean_tenant(tenant_id)
        p_dir = os.path.join(self.projects_dir, safe_tenant)
        os.makedirs(p_dir, exist_ok=True)
        return os.path.join(p_dir, "data.db")

    def _get_conn(self, tenant_id: str) -> sqlite3.Connection:
        db_path = self.get_project_db_path(tenant_id)
        conn = sqlite3.connect(db_path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _invalidate_table(self, tenant_id: str, table_name: str):
        with self._mutex:
            t_key = f"{tenant_id}:{table_name}"
            self._table_versions[t_key] = self._table_versions.get(t_key, 0) + 1

    def _auto_ensure_table(self, conn: sqlite3.Connection, table_name: str, data: dict) -> str:
        safe_table = self._clean_table(table_name)
        cursor = conn.cursor()
        cursor.execute(f"CREATE TABLE IF NOT EXISTS {safe_table} (id TEXT PRIMARY KEY, _doc JSON, _created_at DATETIME DEFAULT CURRENT_TIMESTAMP, _updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute(f"PRAGMA table_info({safe_table})")
        existing_cols = {r[1].lower() for r in cursor.fetchall()}

        if isinstance(data, dict):
            for k, v in data.items():
                safe_col = re.sub(r'[^a-zA-Z0-9_]', '', str(k).strip())
                if not safe_col or safe_col.lower() in existing_cols or safe_col in ["id", "_doc", "_created_at", "_updated_at"]:
                    continue
                col_type = "TEXT"
                if isinstance(v, bool):
                    col_type = "INTEGER"
                elif isinstance(v, int):
                    col_type = "INTEGER"
                elif isinstance(v, float):
                    col_type = "REAL"
                elif isinstance(v, (dict, list)):
                    col_type = "JSON"
                try:
                    cursor.execute(f"ALTER TABLE {safe_table} ADD COLUMN {safe_col} {col_type}")
                    existing_cols.add(safe_col.lower())
                except Exception:
                    pass
        return safe_table

    # =========================================================================
    # CORE CRUD OPERATIONS
    # =========================================================================

    def set(self, tenant_id: str, table_name: str, key: str, data: Any, ttl: Optional[int] = None) -> dict:
        t0 = time.perf_counter()
        safe_tenant = self._clean_tenant(tenant_id)
        safe_table = self._clean_table(table_name)
        safe_key = str(key).strip()
        if not safe_key:
            raise ValueError("Document key cannot be empty")

        doc_payload = data if isinstance(data, dict) else {"value": data}
        doc_payload["id"] = safe_key
        doc_payload["_key"] = safe_key

        # 1. Update L1 In-Memory Cache
        cache_key = f"{safe_tenant}:{safe_table}:{safe_key}"
        exp_time = (time.time() + ttl) if ttl and ttl > 0 else None
        with self._mutex:
            self._cache[cache_key] = (doc_payload, exp_time)

        self._invalidate_table(safe_tenant, safe_table)

        # 2. Persist to SQLite WAL L2 Storage
        p_lock = self._get_project_lock(safe_tenant)
        with p_lock:
            conn = self._get_conn(safe_tenant)
            try:
                real_table = self._auto_ensure_table(conn, safe_table, doc_payload)
                cursor = conn.cursor()
                cursor.execute(f"PRAGMA table_info({real_table})")
                table_cols = [r[1] for r in cursor.fetchall() if r[1] not in ["_created_at", "_updated_at"]]

                insert_cols = []
                insert_vals = []
                for col in table_cols:
                    if col == "id":
                        insert_cols.append("id")
                        insert_vals.append(safe_key)
                    elif col == "_doc":
                        insert_cols.append("_doc")
                        insert_vals.append(json.dumps(doc_payload))
                    elif col in doc_payload:
                        val = doc_payload[col]
                        insert_cols.append(col)
                        insert_vals.append(json.dumps(val) if isinstance(val, (dict, list)) else val)

                placeholders = ", ".join(["?"] * len(insert_cols))
                cols_joined = ", ".join(insert_cols)
                updates_joined = ", ".join([f"{c} = excluded.{c}" for c in insert_cols if c != "id"])

                sql = f"INSERT INTO {real_table} ({cols_joined}, _updated_at) VALUES ({placeholders}, CURRENT_TIMESTAMP)"
                if updates_joined:
                    sql += f" ON CONFLICT(id) DO UPDATE SET {updates_joined}, _updated_at = CURRENT_TIMESTAMP"
                else:
                    sql += f" ON CONFLICT(id) DO UPDATE SET _updated_at = CURRENT_TIMESTAMP"

                cursor.execute(sql, insert_vals)
                conn.commit()
            finally:
                conn.close()

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 3)

        # 3. Publish to Real-time SSE PubSub
        event_payload = {
            "action": "set",
            "table": safe_table,
            "key": safe_key,
            "data": doc_payload,
            "ts": time.time()
        }
        self.pubsub.publish(safe_tenant, safe_table, event_payload)

        return {
            "status": "success",
            "service": "HyperData",
            "table": safe_table,
            "key": safe_key,
            "tier": "RAM L1 + SQLite WAL L2",
            "latency_ms": elapsed_ms,
            "data": doc_payload
        }

    def get(self, tenant_id: str, table_name: str, key: str) -> Optional[dict]:
        t0 = time.perf_counter()
        safe_tenant = self._clean_tenant(tenant_id)
        safe_table = self._clean_table(table_name)
        safe_key = str(key).strip()
        if not safe_key:
            return None

        cache_key = f"{safe_tenant}:{safe_table}:{safe_key}"
        now = time.time()

        # 1. Check L1 Cache
        with self._mutex:
            if cache_key in self._cache:
                doc_payload, exp_time = self._cache[cache_key]
                if exp_time is None or now < exp_time:
                    elapsed_ms = round((time.perf_counter() - t0) * 1000, 3)
                    return {
                        "status": "success",
                        "service": "HyperData",
                        "table": safe_table,
                        "key": safe_key,
                        "cached": True,
                        "tier": "Redis L1 RAM",
                        "latency_ms": elapsed_ms,
                        "data": doc_payload
                    }
                else:
                    del self._cache[cache_key]

        # 2. Check SQLite WAL L2
        p_lock = self._get_project_lock(safe_tenant)
        with p_lock:
            conn = self._get_conn(safe_tenant)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.cursor()
                row = cursor.execute(f"SELECT * FROM {safe_table} WHERE id = ?", (safe_key,)).fetchone()
                if not row:
                    return None
                row_dict = dict(row)
                doc_data = None
                if "_doc" in row_dict and row_dict["_doc"]:
                    try:
                        doc_data = json.loads(row_dict["_doc"])
                    except Exception:
                        pass
                if not doc_data:
                    doc_data = {k: v for k, v in row_dict.items() if not k.startswith("_")}

                # Populate L1 cache with 1 hour default expiration
                with self._mutex:
                    self._cache[cache_key] = (doc_data, now + 3600)

                elapsed_ms = round((time.perf_counter() - t0) * 1000, 3)
                return {
                    "status": "success",
                    "service": "HyperData",
                    "table": safe_table,
                    "key": safe_key,
                    "cached": False,
                    "tier": "SQLite WAL L2",
                    "latency_ms": elapsed_ms,
                    "data": doc_data
                }
            except Exception:
                return None
            finally:
                conn.close()

    def delete(self, tenant_id: str, table_name: str, key: str) -> dict:
        t0 = time.perf_counter()
        safe_tenant = self._clean_tenant(tenant_id)
        safe_table = self._clean_table(table_name)
        safe_key = str(key).strip()
        if not safe_key:
            return {"status": "error", "error": "Document key cannot be empty"}

        cache_key = f"{safe_tenant}:{safe_table}:{safe_key}"
        with self._mutex:
            self._cache.pop(cache_key, None)

        self._invalidate_table(safe_tenant, safe_table)

        p_lock = self._get_project_lock(safe_tenant)
        with p_lock:
            conn = self._get_conn(safe_tenant)
            try:
                conn.execute(f"DELETE FROM {safe_table} WHERE id = ?", (safe_key,))
                conn.commit()
            except Exception:
                pass
            finally:
                conn.close()

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 3)
        event_payload = {
            "action": "delete",
            "table": safe_table,
            "key": safe_key,
            "ts": time.time()
        }
        self.pubsub.publish(safe_tenant, safe_table, event_payload)

        return {
            "status": "success",
            "service": "HyperData",
            "table": safe_table,
            "key": safe_key,
            "deleted": True,
            "latency_ms": elapsed_ms
        }

    def batch(self, tenant_id: str, table_name: str, items: list, ttl: Optional[int] = None) -> dict:
        t0 = time.perf_counter()
        safe_tenant = self._clean_tenant(tenant_id)
        safe_table = self._clean_table(table_name)
        if not items or not isinstance(items, list):
            raise ValueError("items must be a non-empty list of objects")

        normalized_sets = []
        normalized_deletes = []
        for idx, itm in enumerate(items):
            if not isinstance(itm, dict):
                itm = {"value": itm}
            op = str(itm.get("op", "set")).lower()
            itm_table = self._clean_table(itm.get("table") or safe_table)
            k = str(itm.get("id") or itm.get("key") or itm.get("_key") or f"{int(time.time()*1000)}_{idx}").strip()
            if op == "delete":
                normalized_deletes.append((itm_table, k))
            else:
                doc = itm.get("data") if ("data" in itm and isinstance(itm["data"], dict)) else itm
                doc = dict(doc)
                doc["id"] = k
                doc["_key"] = k
                normalized_sets.append((itm_table, k, doc))

        affected_tables = {safe_table}
        exp_time = (time.time() + ttl) if ttl and ttl > 0 else None

        with self._mutex:
            for itm_t, k, doc in normalized_sets:
                affected_tables.add(itm_t)
                self._cache[f"{safe_tenant}:{itm_t}:{k}"] = (doc, exp_time)
            for itm_t, k in normalized_deletes:
                affected_tables.add(itm_t)
                self._cache.pop(f"{safe_tenant}:{itm_t}:{k}", None)
            for t in affected_tables:
                self._table_versions[f"{safe_tenant}:{t}"] = self._table_versions.get(f"{safe_tenant}:{t}", 0) + 1

        p_lock = self._get_project_lock(safe_tenant)
        processed_keys = []
        with p_lock:
            conn = self._get_conn(safe_tenant)
            try:
                for itm_t, k, doc in normalized_sets:
                    self._auto_ensure_table(conn, itm_t, doc)

                cursor = conn.cursor()
                for itm_t, k, doc in normalized_sets:
                    cursor.execute(f"PRAGMA table_info({itm_t})")
                    table_cols = [r[1] for r in cursor.fetchall() if r[1] not in ["_created_at", "_updated_at"]]
                    insert_cols = []
                    insert_vals = []
                    for col in table_cols:
                        if col == "id":
                            insert_cols.append("id")
                            insert_vals.append(k)
                        elif col == "_doc":
                            insert_cols.append("_doc")
                            insert_vals.append(json.dumps(doc))
                        elif col in doc:
                            val = doc[col]
                            insert_cols.append(col)
                            insert_vals.append(json.dumps(val) if isinstance(val, (dict, list)) else val)
                    placeholders = ", ".join(["?"] * len(insert_cols))
                    cols_joined = ", ".join(insert_cols)
                    updates_joined = ", ".join([f"{c} = excluded.{c}" for c in insert_cols if c != "id"])
                    sql = f"INSERT INTO {itm_t} ({cols_joined}, _updated_at) VALUES ({placeholders}, CURRENT_TIMESTAMP)"
                    if updates_joined:
                        sql += f" ON CONFLICT(id) DO UPDATE SET {updates_joined}, _updated_at = CURRENT_TIMESTAMP"
                    else:
                        sql += f" ON CONFLICT(id) DO UPDATE SET _updated_at = CURRENT_TIMESTAMP"
                    cursor.execute(sql, insert_vals)
                    processed_keys.append(k)

                for itm_t, k in normalized_deletes:
                    try:
                        cursor.execute(f"DELETE FROM {itm_t} WHERE id = ?", (k,))
                        processed_keys.append(k)
                    except Exception:
                        pass

                conn.commit()
            finally:
                conn.close()

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 3)
        for t in affected_tables:
            self.pubsub.publish(safe_tenant, t, {
                "action": "batch",
                "table": t,
                "count": len(processed_keys),
                "keys": processed_keys,
                "ts": time.time()
            })

        return {
            "status": "success",
            "service": "HyperData",
            "table": safe_table,
            "processed": len(processed_keys),
            "keys": processed_keys,
            "tier": "RAM L1 + SQLite WAL L2 Pipelined",
            "latency_ms": elapsed_ms
        }

    def patch(self, tenant_id: str, table_name: str, key: str, patch_data: Optional[dict] = None,
              action: str = "merge", field: Optional[str] = None, value: Any = None) -> dict:
        t0 = time.perf_counter()
        safe_tenant = self._clean_tenant(tenant_id)
        safe_table = self._clean_table(table_name)
        safe_key = str(key).strip()
        if not safe_key:
            raise ValueError("Document key cannot be empty")

        current = self.get(safe_tenant, safe_table, safe_key)
        doc = current.get("data", {}) if current and isinstance(current, dict) else {}
        if not isinstance(doc, dict):
            doc = {"value": doc}
        doc["id"] = safe_key
        doc["_key"] = safe_key

        if action in ["increment", "incr"]:
            f_name = field or (list(patch_data.keys())[0] if isinstance(patch_data, dict) and patch_data else "count")
            inc_by = value if value is not None else (patch_data.get(f_name, 1) if isinstance(patch_data, dict) else 1)
            try:
                cur_num = float(doc.get(f_name, 0))
                new_num = cur_num + float(inc_by)
                doc[f_name] = int(new_num) if new_num.is_integer() else new_num
            except Exception:
                doc[f_name] = inc_by
        elif action == "delete_field":
            f_name = field or value
            if f_name and f_name in doc and f_name not in ["id", "_key"]:
                del doc[f_name]
        else: # merge
            if isinstance(patch_data, dict):
                for k, v in patch_data.items():
                    if k not in ["id", "_key"]:
                        doc[k] = v

        res = self.set(safe_tenant, safe_table, safe_key, doc)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 3)
        res["action"] = action
        res["latency_ms"] = elapsed_ms
        self.pubsub.publish(safe_tenant, safe_table, {
            "action": f"patch:{action}",
            "table": safe_table,
            "key": safe_key,
            "data": doc,
            "ts": time.time()
        })
        return res

    def query(self, tenant_id: str, table_name: str, filter_dict: Optional[dict] = None,
              limit: int = 50, offset: int = 0, order_by: Optional[str] = None,
              sort_desc: bool = False) -> dict:
        t0 = time.perf_counter()
        safe_tenant = self._clean_tenant(tenant_id)
        safe_table = self._clean_table(table_name)
        limit = max(1, min(1000, int(limit)))
        offset = max(0, int(offset))

        # Check Query Cache
        t_key = f"{safe_tenant}:{safe_table}"
        t_ver = self._table_versions.get(t_key, 0)
        q_raw = json.dumps({"f": filter_dict, "l": limit, "o": offset, "ob": order_by, "d": sort_desc}, sort_keys=True)
        q_hash = hashlib.md5(q_raw.encode()).hexdigest()
        cache_key = f"{safe_tenant}:{safe_table}:{t_ver}:{q_hash}"
        now = time.time()

        with self._mutex:
            if cache_key in self._query_cache:
                cached_res, exp = self._query_cache[cache_key]
                if now < exp:
                    res_copy = dict(cached_res)
                    res_copy["cached"] = True
                    res_copy["latency_ms"] = round((time.perf_counter() - t0) * 1000, 3)
                    return res_copy
                else:
                    del self._query_cache[cache_key]

        p_lock = self._get_project_lock(safe_tenant)
        with p_lock:
            conn = self._get_conn(safe_tenant)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.cursor()
                cursor.execute(f"PRAGMA table_info({safe_table})")
                table_cols = {r[1].lower(): r[1] for r in cursor.fetchall()}
                if not table_cols:
                    return {
                        "status": "success",
                        "service": "HyperData",
                        "table": safe_table,
                        "count": 0,
                        "rows": [],
                        "latency_ms": round((time.perf_counter() - t0) * 1000, 3)
                    }

                where_clauses = []
                params = []
                if isinstance(filter_dict, dict):
                    for k, v in filter_dict.items():
                        col_clean = re.sub(r'[^a-zA-Z0-9_]', '', str(k).strip())
                        col_expr = table_cols.get(col_clean.lower(), f"json_extract(_doc, '$.{col_clean}')")

                        if isinstance(v, list):
                            if len(v) == 0:
                                where_clauses.append("1=0")
                            else:
                                placeholders = ", ".join(["?"] * len(v))
                                where_clauses.append(f"{col_expr} IN ({placeholders})")
                                params.extend(v)
                        elif isinstance(v, dict):
                            op = str(v.get("op", "")).lower()
                            val = v.get("val") if "val" in v else v.get("value")
                            if op in ["in"] and isinstance(val, list):
                                if len(val) == 0:
                                    where_clauses.append("1=0")
                                else:
                                    placeholders = ", ".join(["?"] * len(val))
                                    where_clauses.append(f"{col_expr} IN ({placeholders})")
                                    params.extend(val)
                            elif op in ["array-contains", "contains"]:
                                where_clauses.append(f"{col_expr} LIKE ?")
                                params.append(f"%{val}%")
                            elif op in [">=", "gte"]:
                                where_clauses.append(f"{col_expr} >= ?")
                                params.append(val)
                            elif op in ["<=", "lte"]:
                                where_clauses.append(f"{col_expr} <= ?")
                                params.append(val)
                            elif op in [">", "gt"]:
                                where_clauses.append(f"{col_expr} > ?")
                                params.append(val)
                            elif op in ["<", "lt"]:
                                where_clauses.append(f"{col_expr} < ?")
                                params.append(val)
                            elif op in ["!=", "ne"]:
                                where_clauses.append(f"{col_expr} != ?")
                                params.append(val)
                            else:
                                where_clauses.append(f"{col_expr} = ?")
                                params.append(val)
                        else:
                            where_clauses.append(f"{col_expr} = ?")
                            params.append(v)

                sql = f"SELECT * FROM {safe_table}"
                if where_clauses:
                    sql += " WHERE " + " AND ".join(where_clauses)

                if order_by:
                    ob_clean = re.sub(r'[^a-zA-Z0-9_]', '', str(order_by)).lower()
                    real_ob = table_cols.get(ob_clean, f"json_extract(_doc, '$.{ob_clean}')")
                    sql += f" ORDER BY {real_ob} {'DESC' if sort_desc else 'ASC'}"
                else:
                    sql += f" ORDER BY _updated_at {'DESC' if sort_desc else 'ASC'}"

                sql += " LIMIT ? OFFSET ?"
                params.extend([limit, offset])

                cursor.execute(sql, params)
                rows = []
                for r in cursor.fetchall():
                    row_dict = dict(r)
                    if "_doc" in row_dict and row_dict["_doc"]:
                        try:
                            d = json.loads(row_dict["_doc"])
                            rows.append(d)
                            continue
                        except Exception:
                            pass
                    clean_row = {k: v for k, v in row_dict.items() if not k.startswith("_")}
                    rows.append(clean_row)

                res = {
                    "status": "success",
                    "service": "HyperData",
                    "table": safe_table,
                    "count": len(rows),
                    "limit": limit,
                    "offset": offset,
                    "rows": rows,
                    "cached": False,
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 3)
                }

                # Cache query result for 20s
                with self._mutex:
                    self._query_cache[cache_key] = (res, now + 20)

                return res
            except Exception as e:
                return {
                    "status": "error",
                    "service": "HyperData",
                    "error": str(e),
                    "table": safe_table,
                    "count": 0,
                    "rows": []
                }
            finally:
                conn.close()

    def tables(self, tenant_id: str) -> dict:
        t0 = time.perf_counter()
        safe_tenant = self._clean_tenant(tenant_id)
        p_lock = self._get_project_lock(safe_tenant)
        with p_lock:
            conn = self._get_conn(safe_tenant)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
                tables = [r[0] for r in cursor.fetchall()]
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 3)
                return {
                    "status": "success",
                    "service": "HyperData",
                    "tenant_id": safe_tenant,
                    "tables": tables,
                    "count": len(tables),
                    "latency_ms": elapsed_ms
                }
            except Exception as e:
                return {"status": "error", "error": str(e), "tables": [], "count": 0}
            finally:
                conn.close()

    def drop(self, tenant_id: str, table_name: str) -> dict:
        t0 = time.perf_counter()
        safe_tenant = self._clean_tenant(tenant_id)
        safe_table = self._clean_table(table_name)

        # Clear L1 cache keys for this table
        with self._mutex:
            prefix = f"{safe_tenant}:{safe_table}:"
            keys_to_del = [k for k in self._cache.keys() if k.startswith(prefix)]
            for k in keys_to_del:
                del self._cache[k]

        self._invalidate_table(safe_tenant, safe_table)

        p_lock = self._get_project_lock(safe_tenant)
        with p_lock:
            conn = self._get_conn(safe_tenant)
            try:
                conn.execute(f"DROP TABLE IF EXISTS {safe_table};")
                conn.commit()
            except Exception:
                pass
            finally:
                conn.close()

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 3)
        self.pubsub.publish(safe_tenant, safe_table, {
            "action": "drop",
            "table": safe_table,
            "ts": time.time()
        })

        return {
            "status": "success",
            "service": "HyperData",
            "table": safe_table,
            "dropped": True,
            "latency_ms": elapsed_ms
        }

    def status(self, tenant_id: Optional[str] = None) -> dict:
        safe_tenant = self._clean_tenant(tenant_id)
        tbl_res = self.tables(safe_tenant)
        tbl_count = tbl_res.get("count", 0)
        return {
            "status": "ONLINE",
            "service": "HyperData",
            "engine": "Dual-Tier RAM L1 + SQLite WAL L2",
            "tenant_id": safe_tenant,
            "tables_count": tbl_count,
            "storage_dir": self.projects_dir,
            "timestamp": time.time()
        }

    def stream_events(self, tenant_id: str, table_name: str = "*"):
        """Generator yielding SSE formatted strings."""
        safe_tenant = self._clean_tenant(tenant_id)
        safe_table = self._clean_table(table_name) if table_name != "*" else "*"
        q = self.pubsub.subscribe(safe_tenant, safe_table)

        # Initial handshake
        init_payload = json.dumps({
            "type": "connected",
            "service": "HyperData",
            "tenant_id": safe_tenant,
            "table": safe_table
        })
        yield f"data: {init_payload}\n\n"

        try:
            while True:
                try:
                    event = q.get(timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    # Keep-alive heartbeat ping
                    yield ": ping\n\n"
        except GeneratorExit:
            pass
        finally:
            self.pubsub.unsubscribe(safe_tenant, safe_table, q)
