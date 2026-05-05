using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using System;
using System.IO;
using System.Text;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace AICommandLocal
{

/// <summary>
/// Replays HPC JSONL outputs locally without calling any LLM.
///
/// CLI usage:
///   /path/to/Unity -batchmode -nographics \
///     -projectPath /path/to/project \
///     -executeMethod AICommandLocal.BatchRunner.Run \
///     --jsonl results/hpc_runs.jsonl
///
/// The method will call EditorApplication.Exit() when done; do NOT pass -quit.
///
/// State is persisted in EditorPrefs so it survives domain reloads between records.
/// SessionState guards against stale EditorPrefs from a previous crashed run.
/// Iteration is driven by dynamic pending-record lookup rather than a fixed index/total
/// so shrinking pending counts (as compile_pass is patched in) never cause out-of-range aborts.
/// </summary>
[InitializeOnLoad]
static class BatchRunner
{
    const string TempFilePath = "Assets/AICommandLocalTemp.cs";

    // EditorPrefs keys (persist across domain reloads)
    const string PrefActive         = "BatchRunner_Active";
    const string PrefJsonlPath      = "BatchRunner_JsonlPath";
    const string PrefIndex          = "BatchRunner_Index";   // current ordinal (1-based; for logs only)
    const string PrefTotal          = "BatchRunner_Total";   // pending total at last WriteAndCompile; for logs only
    const string PrefRunId          = "BatchRunner_RunId";
    const string PrefPatternId      = "BatchRunner_PatternId";
    const string PrefMethod         = "BatchRunner_Method";
    const string PrefModel          = "BatchRunner_Model";
    const string PrefStartTimeTicks = "BatchRunner_StartTimeTicks";

    // SessionState key (cleared when Unity restarts; guards against stale EditorPrefs)
    const string SessionKey = "BatchRunner_SessionActive";

    // Hard timeout per record waiting for compilation/domain reload (seconds)
    const double CompileTimeoutSecs = 120.0;

    // ── [InitializeOnLoad] fires after every domain reload ────────────────────

    static BatchRunner()
    {
        if (EditorPrefs.GetString(PrefActive, "") != "1") return;

        // Guard: if SessionState lost (editor restarted), clear stale prefs
        if (!SessionState.GetBool(SessionKey, false))
        {
            Debug.LogWarning("[BatchRunner] Stale batch state detected (editor restarted?). Clearing.");
            ClearState();
            return;
        }

        // We just came back from a compilation; continue on next frame
        EditorApplication.delayCall += ContinueBatch;
        // Watchdog: fires each frame in case the next compile/reload hangs
        EditorApplication.update += WatchdogTick;
    }

    // ── Public entry point ────────────────────────────────────────────────────

    /// <summary>
    /// Called via -executeMethod AICommandLocal.BatchRunner.Run.
    /// Do NOT pass -quit; this method exits Unity via EditorApplication.Exit().
    /// </summary>
    public static void Run()
    {
        var jsonlPath = ResolveJsonlPath();
        Debug.Log($"[BatchRunner] Run() — JSONL: {jsonlPath}");

        if (!File.Exists(jsonlPath))
        {
            Debug.LogError($"[BatchRunner] JSONL file not found: {jsonlPath}");
            ExitOrReturn(1);
            return;
        }

        if (!TryGetNextPendingRecord(jsonlPath, out string line, out int ordinal, out int total))
        {
            Debug.Log("[BatchRunner] No pending records — nothing to do.");
            ExitOrReturn(0);
            return;
        }

        Debug.Log($"[BatchRunner] {total} pending record(s) to process.");

        // Persist batch state
        SessionState.SetBool(SessionKey, true);
        EditorPrefs.SetString(PrefActive,    "1");
        EditorPrefs.SetString(PrefJsonlPath, jsonlPath);

        WriteAndCompile(line, ordinal, total);
        // Domain reload fires → [InitializeOnLoad] → ContinueBatch
    }

    // ── State machine: post-compilation step ──────────────────────────────────

    static void ContinueBatch()
    {
        if (EditorPrefs.GetString(PrefActive, "") != "1") return;

        // Domain reload happened — watchdog no longer needed for this record
        EditorApplication.update -= WatchdogTick;

        var runId     = EditorPrefs.GetString(PrefRunId,     "");
        var patternId = EditorPrefs.GetString(PrefPatternId, "_debug");
        var method    = EditorPrefs.GetString(PrefMethod,    "no_schema");
        var model     = EditorPrefs.GetString(PrefModel,     "");
        var ordinal   = EditorPrefs.GetInt   (PrefIndex,     0);
        var total     = EditorPrefs.GetInt   (PrefTotal,     0);
        var jsonlPath = EditorPrefs.GetString(PrefJsonlPath, "");

        // ── 1. Detect compile result BEFORE attempting task execution ─────────
        int cp = string.IsNullOrEmpty(runId) ? -1 : RunLogger.DetectCompilePass(runId);
        string compileError = "";

        if (cp == 0)
        {
            compileError = RunLogger.ExtractCompileErrors(runId);
            Debug.LogWarning($"[BatchRunner] [{ordinal}/{total} pending] Compile failed — run_id={runId} errors: {compileError}");
        }
        else
        {
            // ── 2. Execute generated script ───────────────────────────────────
            bool taskExecuted = false;
            try
            {
                if (EditorApplication.ExecuteMenuItem("Edit/Do Task"))
                {
                    Debug.Log($"[BatchRunner] [{ordinal}/{total} pending] Edit/Do Task: OK");
                    taskExecuted = true;
                }
                else
                {
                    Debug.LogWarning($"[BatchRunner] [{ordinal}/{total} pending] Edit/Do Task: not found (compile/runtime error)");
                }
            }
            catch (Exception ex)
            {
                Debug.LogError($"[BatchRunner] [{ordinal}/{total} pending] Edit/Do Task exception: {ex.Message}");
            }

            // ── 3. Export generated scene ─────────────────────────────────────
            if (taskExecuted && !string.IsNullOrEmpty(runId) && patternId != "_debug")
                ExportScene(runId, patternId, method, model);

            // Refine cp from task result when log marker was missing
            if (cp < 0) cp = taskExecuted ? 1 : 0;
        }

        // ── 4. Record compile_pass (and error summary) ────────────────────────
        if (!string.IsNullOrEmpty(runId))
        {
            if (cp < 0) cp = 0;  // final fallback
            RunLogger.UpdateCompilePass(runId, cp, method, jsonlPath);
            if (cp == 0 && !string.IsNullOrEmpty(compileError))
                RunLogger.UpdateCompileError(runId, compileError, method, jsonlPath);
            Debug.Log($"[BatchRunner] compile_pass={cp}  run_id={runId}");
        }

        // ── 5. Clean up temp script ───────────────────────────────────────────
        CleanupTempFiles();

        // ── 6. Re-read JSONL for next pending record (dynamic lookup) ─────────
        if (!TryGetNextPendingRecord(jsonlPath, out string nextLine, out int nextOrdinal, out int nextTotal))
        {
            Debug.Log("[BatchRunner] Batch complete — no pending records remain.");
            ClearState();
            ExitOrReturn(0);
            return;
        }

        WriteAndCompile(nextLine, nextOrdinal, nextTotal);
    }

    // ── Watchdog: fires every editor frame while waiting for compile/reload ───

    static void WatchdogTick()
    {
        if (EditorPrefs.GetString(PrefActive, "") != "1")
        {
            EditorApplication.update -= WatchdogTick;
            return;
        }

        var ticksStr = EditorPrefs.GetString(PrefStartTimeTicks, "");
        if (string.IsNullOrEmpty(ticksStr)) return;

        if (!long.TryParse(ticksStr, out long startTicks)) return;

        var elapsed = TimeSpan.FromTicks(DateTime.UtcNow.Ticks - startTicks).TotalSeconds;
        if (elapsed <= CompileTimeoutSecs) return;

        EditorApplication.update -= WatchdogTick;
        var runId = EditorPrefs.GetString(PrefRunId, "");
        Debug.LogError($"[BatchRunner] Compile watchdog triggered after {elapsed:F0}s — run_id={runId}. Forcing timeout record.");
        ForceTimeoutRecord();
    }

    static void ForceTimeoutRecord()
    {
        var runId     = EditorPrefs.GetString(PrefRunId,     "");
        var method    = EditorPrefs.GetString(PrefMethod,    "no_schema");
        var jsonlPath = EditorPrefs.GetString(PrefJsonlPath, "");

        if (!string.IsNullOrEmpty(runId))
        {
            RunLogger.UpdateCompilePass(runId, 0, method, jsonlPath);
            RunLogger.UpdateCompileTimeout(runId, method, jsonlPath);
        }

        CleanupTempFiles();

        // Re-read JSONL for next pending record (dynamic lookup)
        if (!TryGetNextPendingRecord(jsonlPath, out string nextLine, out int nextOrdinal, out int nextTotal))
        {
            Debug.Log("[BatchRunner] Batch complete (after timeout) — no pending records remain.");
            ClearState();
            ExitOrReturn(0);
            return;
        }

        WriteAndCompile(nextLine, nextOrdinal, nextTotal);
    }

    // ── Write temp script and trigger compilation ─────────────────────────────

    static void WriteAndCompile(string jsonLine, int ordinal, int total)
    {
        var runId     = ExtractStringField(jsonLine, "run_id")      ?? DateTime.UtcNow.ToString("yyyyMMdd_HHmmss_fff");
        var patternId = ExtractStringField(jsonLine, "pattern_id")  ?? "_debug";
        var method    = ExtractStringField(jsonLine, "method")      ?? "no_schema";
        var model     = ExtractStringField(jsonLine, "model")       ?? "";
        var code      = ExtractStringField(jsonLine, "output_code") ?? "";

        if (string.IsNullOrEmpty(patternId)) patternId = "_debug";
        if (string.IsNullOrEmpty(method))    method    = "no_schema";

        Debug.Log($"[BatchRunner] [{ordinal}/{total} pending] run_id={runId}  pattern={patternId}  method={method}");
        Debug.Log($"AICommandRunStart:{runId}");  // Marker scanned by DetectCompilePass

        // Persist metadata for ContinueBatch after domain reload
        EditorPrefs.SetString(PrefRunId,          runId);
        EditorPrefs.SetString(PrefPatternId,      patternId);
        EditorPrefs.SetString(PrefMethod,         method);
        EditorPrefs.SetString(PrefModel,          model);
        EditorPrefs.SetString(PrefStartTimeTicks, DateTime.UtcNow.Ticks.ToString());
        EditorPrefs.SetInt   (PrefIndex,          ordinal);  // for log display only
        EditorPrefs.SetInt   (PrefTotal,          total);    // for log display only

        // ── Log batch run record (compile_pass written as null; patched later) ─
        var batchJsonlPath = EditorPrefs.GetString(PrefJsonlPath, "");
        RunLogger.LogBatchRun(runId, patternId, method, code, batchJsonlPath);

        // ── Write output_code to temp script ──────────────────────────────────
        var cleanCode = SanitizeGeneratedCode(code, out var sanitizeReason);
        if (string.IsNullOrEmpty(cleanCode))
        {
            // Write a tagged #error placeholder so compile failure is explicit and
            // machine-attributable for failure taxonomy (rather than hanging).
            var tag = string.IsNullOrEmpty(sanitizeReason) ? "empty_after_sanitize" : sanitizeReason;
            Debug.LogWarning($"[BatchRunner] [{ordinal}/{total} pending] Sanitizer produced no compilable code ({tag}) — run_id={runId}");
            cleanCode = $"#error BatchRunner_sanitize_{tag} run_id={runId}";
        }

        // Remove any stale temp files before writing the fresh one
        CleanupTempFiles();

        File.WriteAllText(TempFilePath, cleanCode);
        AssetDatabase.Refresh();
        // Register watchdog in case the domain reload / compilation hangs
        EditorApplication.update += WatchdogTick;
        // Domain reload → [InitializeOnLoad] → ContinueBatch
    }

    // ── Clean up temp scripts (file-level delete; no extra AssetDB refresh) ───

    static void CleanupTempFiles()
    {
        foreach (var pattern in new[] { "AICommandLocalTemp*.cs", "AICommandLocalTemp*.cs.meta" })
        {
            foreach (var file in Directory.GetFiles("Assets", pattern))
            {
                try { File.Delete(file); }
                catch (Exception ex)
                {
                    Debug.LogWarning($"[BatchRunner] CleanupTempFiles: could not delete {file}: {ex.Message}");
                }
            }
        }
    }

    // ── Scene export ──────────────────────────────────────────────────────────

    static void ExportScene(string runId, string patternId, string method, string model)
    {
        try
        {
            var modelDir = string.IsNullOrEmpty(model) ? "unknown_model" : model;
            var dir = Path.Combine(
                RunLogger.ProjectRoot,
                "results", "unity_generated", modelDir, patternId, method, runId);
            Directory.CreateDirectory(dir);

            var scenePath = Path.Combine(dir, "scene.unity");
            var scene = EditorSceneManager.GetActiveScene();
            EditorSceneManager.SaveScene(scene, scenePath, true);
            Debug.Log($"[BatchRunner] Scene exported: {scenePath}");
        }
        catch (Exception ex)
        {
            Debug.LogWarning($"[BatchRunner] Scene export failed (non-fatal): {ex.Message}");
        }
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    /// <summary>
    /// Re-reads the JSONL and returns the first pending record.
    /// A record is pending if it has output_code AND (no compile_pass field OR compile_pass:null).
    /// Returns false when no pending records remain — the caller should exit cleanly with code 0.
    /// ordinal (1-based) and total reflect the current pending set size (for log display only).
    /// </summary>
    static bool TryGetNextPendingRecord(string jsonlPath, out string line, out int ordinal, out int total)
    {
        line    = null;
        ordinal = 0;
        total   = 0;

        var pending = ReadNonEmptyLines(jsonlPath);  // already filters to pending-only
        total = pending.Count;
        if (total == 0) return false;

        line    = pending[0];
        ordinal = 1;
        return true;
    }

    static string ResolveJsonlPath()
    {
        // 1. --jsonl <path> command-line arg
        var args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length - 1; i++)
            if (args[i] == "--jsonl") return ResolveJsonlRelative(args[i + 1]);

        // 2. BATCH_JSONL environment variable
        var env = Environment.GetEnvironmentVariable("BATCH_JSONL");
        if (!string.IsNullOrEmpty(env)) return ResolveJsonlRelative(env);

        // 3. Default fallback
        return Path.Combine(RunLogger.ProjectRoot, "results", "hpc_runs.jsonl");
    }

    static string ResolveJsonlRelative(string path)
    {
        if (string.IsNullOrEmpty(path)) return path;
        if (Path.IsPathRooted(path)) return path;

        // 1) Try Unity project root (current working directory for batchmode)
        var cwd = Directory.GetCurrentDirectory();
        var cwdPath = Path.Combine(cwd, path);
        if (File.Exists(cwdPath)) return cwdPath;

        // 2) Try repo root (RunLogger.ProjectRoot)
        var repoPath = Path.Combine(RunLogger.ProjectRoot, path);
        if (File.Exists(repoPath)) return repoPath;

        // 3) Fallback to original relative path
        return path;
    }

    /// <summary>
    /// Returns one representative (output_code-bearing) line per pending run_id.
    /// A run_id is done if ANY line for it has a concrete compile_pass (0 or 1),
    /// tolerating whitespace around the colon (handles pretty-printed HPC records).
    /// Two-pass: first collect done run_ids, then emit pending lines in file order.
    /// </summary>
    static List<string> ReadNonEmptyLines(string path)
    {
        if (!File.Exists(path)) return new List<string>();

        var allLines = File.ReadAllLines(path);

        // Pass 1: identify every run_id that has a concrete compile_pass in any of its lines.
        var doneRunIds = new HashSet<string>();
        foreach (var rawLine in allLines)
        {
            var t = rawLine.Trim();
            if (string.IsNullOrEmpty(t)) continue;
            if (!Regex.IsMatch(t, "\"compile_pass\"\\s*:\\s*[01]")) continue;
            var id = ExtractStringField(t, "run_id");
            if (id != null) doneRunIds.Add(id);
        }

        // Pass 2: emit the first output_code line for each pending run_id, in file order.
        var result  = new List<string>();
        var seen    = new HashSet<string>();
        foreach (var rawLine in allLines)
        {
            var t = rawLine.Trim();
            if (string.IsNullOrEmpty(t)) continue;
            if (!t.Contains("\"output_code\"")) continue;
            var id = ExtractStringField(t, "run_id");
            if (id == null) continue;
            if (doneRunIds.Contains(id)) continue;
            if (!seen.Add(id)) continue;  // emit only first line per run_id
            result.Add(t);
        }
        return result;
    }

    /// <summary>
    /// Extracts a JSON string field value using character-by-character scanning
    /// so it handles large output_code values reliably.
    /// </summary>
    static string ExtractStringField(string json, string field)
    {
        var key = "\"" + field + "\"";
        int keyIdx = json.IndexOf(key, StringComparison.Ordinal);
        if (keyIdx < 0) return null;

        int pos = keyIdx + key.Length;

        // Skip whitespace and colon
        while (pos < json.Length && (json[pos] == ' ' || json[pos] == '\t' || json[pos] == ':')) pos++;

        // Expect opening quote
        if (pos >= json.Length || json[pos] != '"') return null;
        pos++; // skip opening quote

        // Read until unescaped closing quote
        var sb = new StringBuilder();
        while (pos < json.Length)
        {
            char c = json[pos];
            if (c == '\\' && pos + 1 < json.Length)
            {
                pos++;
                switch (json[pos])
                {
                    case '"':  sb.Append('"');  break;
                    case '\\': sb.Append('\\'); break;
                    case '/':  sb.Append('/');  break;
                    case 'n':  sb.Append('\n'); break;
                    case 'r':  sb.Append('\r'); break;
                    case 't':  sb.Append('\t'); break;
                    case 'b':  sb.Append('\b'); break;
                    case 'f':  sb.Append('\f'); break;
                    case 'u':
                        if (pos + 4 < json.Length)
                        {
                            var hex = json.Substring(pos + 1, 4);
                            sb.Append((char)Convert.ToInt32(hex, 16));
                            pos += 4;
                        }
                        break;
                    default: sb.Append(json[pos]); break;
                }
            }
            else if (c == '"')
            {
                break; // end of string value
            }
            else
            {
                sb.Append(c);
            }
            pos++;
        }
        return sb.ToString();
    }

    static string StripMarkdownFences(string code)
    {
        if (string.IsNullOrEmpty(code)) return code;

        // Extract content of the first complete fenced block (any language tag or none).
        // [\s\S]*? is lazy so it stops at the first closing ```.
        var blockMatch = Regex.Match(code, @"^\s*```[^\n]*\n([\s\S]*?)```");
        if (blockMatch.Success)
            return blockMatch.Groups[1].Value.Trim();

        // No complete fenced block; strip any lone opening/closing fence lines everywhere.
        code = Regex.Replace(code, @"^\s*```[^\n]*\n?", "", RegexOptions.IgnoreCase | RegexOptions.Multiline);
        code = Regex.Replace(code, @"\n?\s*```\s*$", "", RegexOptions.Multiline);
        return code.Trim();
    }

    // Normalize model outputs into "best effort" raw C#.
    // Returns null/empty if no plausible compilable fragment is found.
    static string SanitizeGeneratedCode(string code, out string reason)
    {
        reason = "";
        if (string.IsNullOrWhiteSpace(code))
        {
            reason = "empty_input";
            return "";
        }

        var cleaned = StripMarkdownFences(code ?? "");
        if (string.IsNullOrWhiteSpace(cleaned))
        {
            reason = "empty_after_fence_strip";
            return "";
        }

        // Remove obvious markdown prose wrappers that commonly leak from LLM output.
        cleaned = Regex.Replace(cleaned, @"(?im)^\s*(#|##|###)\s+.*$", "");
        cleaned = Regex.Replace(cleaned, @"(?im)^\s*This script.*$", "");
        cleaned = Regex.Replace(cleaned, @"(?im)^\s*Here(?:'s| is)\b.*$", "");
        cleaned = Regex.Replace(cleaned, @"(?im)^\s*Note:\s*.*$", "");
        cleaned = cleaned.Trim();

        // Find the first plausible C# start line and drop preamble prose.
        // Accept attributes, using, namespace, class/struct/interface/enum declarations.
        var start = Regex.Match(
            cleaned,
            @"(?im)^\s*(?:\[[^\]]+\]\s*$|using\s+[A-Za-z_][\w\.]*\s*;|namespace\s+[A-Za-z_][\w\.]*|(?:public|internal|private|protected|static|sealed|partial|abstract)\s+(?:class|struct|interface|enum)\s+[A-Za-z_]\w*|(?:class|struct|interface|enum)\s+[A-Za-z_]\w*|#(?:if|endif|define|undef|pragma)\b)"
        );
        if (start.Success)
        {
            cleaned = cleaned.Substring(start.Index).Trim();
        }
        else
        {
            reason = "no_csharp_start";
            return "";
        }

        // Drop trailing prose after code when possible by cutting at the last "}".
        var lastBrace = cleaned.LastIndexOf('}');
        if (lastBrace > 0)
            cleaned = cleaned.Substring(0, lastBrace + 1).Trim();

        // Any leftover markdown fence token indicates malformed output.
        if (cleaned.Contains("```"))
        {
            reason = "residual_fence_token";
            return "";
        }

        if (cleaned.TrimStart().StartsWith("`"))
        {
            reason = "leading_backtick_after_sanitize";
            return "";
        }

        // Must contain at least one structural C# token.
        if (!Regex.IsMatch(cleaned, @"\b(class|struct|interface|enum|namespace)\b"))
        {
            reason = "missing_type_or_namespace";
            return "";
        }

        return cleaned;
    }

    static void ClearState()
    {
        EditorApplication.update -= WatchdogTick;
        SessionState.EraseBool(SessionKey);
        EditorPrefs.DeleteKey(PrefActive);
        EditorPrefs.DeleteKey(PrefJsonlPath);
        EditorPrefs.DeleteKey(PrefIndex);
        EditorPrefs.DeleteKey(PrefTotal);
        EditorPrefs.DeleteKey(PrefRunId);
        EditorPrefs.DeleteKey(PrefPatternId);
        EditorPrefs.DeleteKey(PrefMethod);
        EditorPrefs.DeleteKey(PrefModel);
        EditorPrefs.DeleteKey(PrefStartTimeTicks);
    }

    static void ExitOrReturn(int code)
    {
        if (Application.isBatchMode)
            EditorApplication.delayCall += () => EditorApplication.Exit(code);
    }
}

} // namespace AICommandLocal
