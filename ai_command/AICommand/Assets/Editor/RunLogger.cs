using UnityEngine;
using System;
using System.IO;
using System.Text.RegularExpressions;

namespace AICommandLocal {

static class RunLogger
{
    // Resolve project root (four levels above Application.dataPath which is .../Assets)
    public static string ProjectRoot
        => Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "..", ".."));

    static string EvalDir => Path.Combine(ProjectRoot, "results", "evaluation");
    static string JsonlPathFor(string method) => Path.Combine(EvalDir, method + "_runs.jsonl");

    public static void LogRun(ChatResult result, string prompt, string logFilePath, string runId)
    {
        var method = ExtractMethod(prompt);
        LogRun(result, prompt, logFilePath, runId, method);
    }

    public static void LogRun(ChatResult result, string prompt, string logFilePath, string runId, string method)
    {
        var settings = AICommandSettings.instance;
        var timestamp = DateTime.UtcNow.ToString("o");

        // Save raw response JSON
        var runDir = Path.Combine(EvalDir, "runs", runId);
        Directory.CreateDirectory(runDir);
        var responsePath = Path.Combine(runDir, "response.json");
        File.WriteAllText(responsePath, result.rawJson ?? "");

        // Build JSONL record (compile_pass written as null; patched after assembly reload)
        var resp = result.parsedResponse;
        var model = !string.IsNullOrEmpty(resp.model) ? resp.model : settings.modelName;
        var respId = resp.id ?? "";
        var created = resp.created;
        var promptTokens = resp.usage.prompt_tokens;
        var completionTokens = resp.usage.completion_tokens;
        var totalTokens = resp.usage.total_tokens;

        var jsonLine = "{"
            + Q("run_id") + ":" + Q(runId)
            + "," + Q("pattern_id") + ":" + Q(ExtractPatternId(prompt))
            + "," + Q("method") + ":" + Q(Esc(method))
            + "," + Q("model") + ":" + Q(Esc(model))
            + "," + Q("seed") + ":null"
            + "," + Q("compile_pass") + ":null"
            + "," + Q("structure_score") + ":null"
            + "," + Q("log_path") + ":" + Q(Esc(logFilePath ?? ""))
            + "," + Q("timestamp") + ":" + Q(timestamp)
            + "," + Q("response_id") + ":" + Q(Esc(respId))
            + "," + Q("response_created") + ":" + created
            + "," + Q("usage") + ":{"
                + Q("prompt_tokens") + ":" + promptTokens
                + "," + Q("completion_tokens") + ":" + completionTokens
                + "," + Q("total_tokens") + ":" + totalTokens
            + "}"
            + "," + Q("latency_ms") + ":" + result.latencyMs
            + "," + Q("endpoint") + ":" + Q(Esc(settings.apiBaseUrl))
            + "," + Q("prompt") + ":" + Q(Esc(prompt))
            + "}";

        Directory.CreateDirectory(EvalDir);
        File.AppendAllText(JsonlPathFor(method), jsonLine + "\n");

        Debug.Log($"Run record written: {runId}  (latency {result.latencyMs}ms)");
    }

    /// <summary>
    /// Patches compile_pass for a previously written run in the JSONL file.
    /// </summary>
    public static void UpdateCompilePass(string runId, int compilePass, string method = "no_schema")
        => UpdateCompilePass(runId, compilePass, method, JsonlPathFor(method));

    /// <summary>
    /// Patches compile_pass in an explicit JSONL file (used by BatchRunner to write back to the input file).
    /// </summary>
    public static void UpdateCompilePass(string runId, int compilePass, string method, string jsonlPath)
    {
        if (string.IsNullOrEmpty(runId) || !File.Exists(jsonlPath)) return;

        var lines = new System.Collections.Generic.List<string>(File.ReadAllLines(jsonlPath));
        for (int i = lines.Count - 1; i >= 0; i--)
        {
            if (!LineMatchesRunId(lines[i], runId)) continue;

            var line = lines[i];
            if (Regex.IsMatch(line, "\"compile_pass\"\\s*:\\s*null"))
            {
                // Record written by LogBatchRun — replace null placeholder
                lines[i] = Regex.Replace(line, "\"compile_pass\"\\s*:\\s*null",
                                         "\"compile_pass\":" + compilePass);
            }
            else if (!line.Contains("\"compile_pass\""))
            {
                // Input seed record — field absent; append before closing }
                if (line.EndsWith("}"))
                    lines[i] = line.Substring(0, line.Length - 1)
                               + ",\"compile_pass\":" + compilePass + "}";
            }
            // else: already set to a concrete value — leave it (idempotent)

            File.WriteAllLines(jsonlPath, lines);
            Debug.Log($"compile_pass updated to {compilePass} for run {runId}");
            return;
        }
    }

    /// <summary>
    /// Reads Editor.log after the last run marker and collects up to maxErrors
    /// compile error lines matching "error CS\d+".
    /// Returns a "; "-joined summary, or "" if none found.
    /// </summary>
    public static string ExtractCompileErrors(string runId, int maxErrors = 3)
    {
        var editorLog = GetEditorLogPath();
        if (editorLog == null || !File.Exists(editorLog)) return "";

        string content;
        using (var fs = new FileStream(editorLog, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
        using (var reader = new System.IO.StreamReader(fs, System.Text.Encoding.UTF8))
            content = reader.ReadToEnd();

        var marker = "AICommandRunStart:" + runId;
        var markerIdx = content.LastIndexOf(marker, StringComparison.Ordinal);
        if (markerIdx < 0) return "";

        var slice = content.Substring(markerIdx + marker.Length);
        var errors = new System.Collections.Generic.List<string>();
        foreach (System.Text.RegularExpressions.Match m in Regex.Matches(slice, @"error CS\d+[^\n]*"))
        {
            errors.Add(m.Value.Trim());
            if (errors.Count >= maxErrors) break;
        }
        return string.Join("; ", errors);
    }

    /// <summary>
    /// Patches the last JSONL record for runId to append a "compile_error" field.
    /// </summary>
    public static void UpdateCompileError(string runId, string errorSummary, string method = "no_schema")
        => UpdateCompileError(runId, errorSummary, method, JsonlPathFor(method));

    /// <summary>
    /// Patches compile_error in an explicit JSONL file (used by BatchRunner to write back to the input file).
    /// </summary>
    public static void UpdateCompileError(string runId, string errorSummary, string method, string jsonlPath)
    {
        if (string.IsNullOrEmpty(runId) || !File.Exists(jsonlPath)) return;

        var lines = new System.Collections.Generic.List<string>(File.ReadAllLines(jsonlPath));
        for (int i = lines.Count - 1; i >= 0; i--)
        {
            if (LineMatchesRunId(lines[i], runId))
            {
                var line = lines[i];
                if (line.EndsWith("}"))
                    line = line.Substring(0, line.Length - 1)
                           + "," + Q("compile_error") + ":" + Q(Esc(errorSummary))
                           + "}";
                lines[i] = line;
                File.WriteAllLines(jsonlPath, lines);
                Debug.Log($"compile_error updated for run {runId}");
                return;
            }
        }
    }

    /// <summary>
    /// Patches the last JSONL record for runId to append "compile_timeout":true.
    /// </summary>
    public static void UpdateCompileTimeout(string runId, string method = "no_schema")
        => UpdateCompileTimeout(runId, method, JsonlPathFor(method));

    /// <summary>
    /// Patches compile_timeout in an explicit JSONL file (used by BatchRunner to write back to the input file).
    /// </summary>
    public static void UpdateCompileTimeout(string runId, string method, string jsonlPath)
    {
        if (string.IsNullOrEmpty(runId) || !File.Exists(jsonlPath)) return;

        var lines = new System.Collections.Generic.List<string>(File.ReadAllLines(jsonlPath));
        for (int i = lines.Count - 1; i >= 0; i--)
        {
            if (LineMatchesRunId(lines[i], runId))
            {
                var line = lines[i];
                if (line.EndsWith("}"))
                    line = line.Substring(0, line.Length - 1)
                           + "," + Q("compile_timeout") + ":true"
                           + "}";
                lines[i] = line;
                File.WriteAllLines(jsonlPath, lines);
                Debug.Log($"compile_timeout set for run {runId}");
                return;
            }
        }
    }

    /// <summary>
    /// Reads Editor.log, finds the last "AICommandRunStart:{runId}" marker,
    /// and scans only content after it for compile errors.
    /// Returns -1 if Editor.log or marker missing, 0 if errors found, 1 otherwise.
    /// </summary>
    public static int DetectCompilePass(string runId)
    {
        var editorLog = GetEditorLogPath();
        if (editorLog == null || !File.Exists(editorLog))
            return -1;

        string content;
        using (var fs = new FileStream(editorLog, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
        using (var reader = new StreamReader(fs, System.Text.Encoding.UTF8))
            content = reader.ReadToEnd();

        var marker = "AICommandRunStart:" + runId;
        var markerIdx = content.LastIndexOf(marker, StringComparison.Ordinal);
        if (markerIdx < 0)
            return -1;

        var slice = content.Substring(markerIdx + marker.Length);
        if (Regex.IsMatch(slice, @"error CS\d+") &&
            slice.Contains("AICommandLocalTemp.cs"))
            return 0;

        return 1;
    }

    static string GetEditorLogPath()
    {
        switch (Application.platform)
        {
            case RuntimePlatform.OSXEditor:
                var home = Environment.GetFolderPath(Environment.SpecialFolder.Personal);
                return Path.Combine(home, "Library", "Logs", "Unity", "Editor.log");
            case RuntimePlatform.WindowsEditor:
                var localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                return Path.Combine(localAppData, "Unity", "Editor", "Editor.log");
            case RuntimePlatform.LinuxEditor:
                var config = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
                if (string.IsNullOrEmpty(config))
                    config = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Personal), ".config");
                return Path.Combine(config, "unity3d", "Editor.log");
            default:
                return null;
        }
    }

    public static string ExtractPatternId(string prompt)
    {
        if (string.IsNullOrEmpty(prompt)) return "_debug";

        // 1. JSON-style: look for "scene": "<id>"
        var jsonMatch = Regex.Match(prompt, @"""scene""\s*:\s*""([^""]+)""", RegexOptions.IgnoreCase);
        if (jsonMatch.Success)
            return jsonMatch.Groups[1].Value.Trim();

        // 2. Tag-style: [pattern: <id>]
        var tagMatch = Regex.Match(prompt, @"\[pattern:\s*([^\]]+)\]", RegexOptions.IgnoreCase);
        if (tagMatch.Success)
            return tagMatch.Groups[1].Value.Trim();

        return "_debug";
    }

    /// <summary>
    /// Extracts method from prompt tag [method: &lt;value&gt;].
    /// Returns "no_schema" if no tag is found.
    /// </summary>
    public static string ExtractMethod(string prompt)
    {
        if (string.IsNullOrEmpty(prompt)) return "no_schema";

        var match = Regex.Match(prompt, @"\[method:\s*([^\]]+)\]", RegexOptions.IgnoreCase);
        if (match.Success)
        {
            var val = match.Groups[1].Value.Trim();
            if (!string.IsNullOrEmpty(val))
                return val;
        }

        return "no_schema";
    }

    /// <summary>
    /// Logs a record for a batch run sourced from HPC output (no LLM involved).
    /// compile_pass is written as null and patched after compilation via UpdateCompilePass.
    /// The raw output_code is saved to results/evaluation/runs/&lt;runId&gt;/output_code.cs.
    /// </summary>
    public static void LogBatchRun(string runId, string patternId, string method, string outputCode)
        => LogBatchRun(runId, patternId, method, outputCode, null);

    /// <summary>
    /// Logs a batch run record into an explicit JSONL file.
    /// When jsonlPath is the input seed file, the run_id already exists so no new
    /// record is appended — only the output_code.cs artefact is saved to disk.
    /// When jsonlPath is null the default method-based path is used.
    /// </summary>
    public static void LogBatchRun(string runId, string patternId, string method, string outputCode, string jsonlPath)
    {
        if (string.IsNullOrEmpty(method))    method    = "no_schema";
        if (string.IsNullOrEmpty(patternId)) patternId = "_debug";

        var timestamp  = DateTime.UtcNow.ToString("o");
        var targetPath = string.IsNullOrEmpty(jsonlPath) ? JsonlPathFor(method) : jsonlPath;

        // Save output code for reference
        var runDir = Path.Combine(EvalDir, "runs", runId);
        Directory.CreateDirectory(runDir);
        File.WriteAllText(Path.Combine(runDir, "output_code.cs"), outputCode ?? "");

        // If this run_id already exists in the JSONL, do not append a duplicate record.
        // Use whitespace-tolerant matching to handle pretty-printed HPC seed records.
        if (File.Exists(targetPath))
        {
            foreach (var line in File.ReadLines(targetPath))
            {
                if (LineMatchesRunId(line, runId))
                {
                    Debug.Log($"Batch run record already exists for run_id={runId}; skipping append.");
                    return;
                }
            }
        }

        var jsonLine = "{"
            + Q("run_id")            + ":" + Q(runId)
            + "," + Q("pattern_id") + ":" + Q(Esc(patternId))
            + "," + Q("method")     + ":" + Q(Esc(method))
            + "," + Q("model")      + ":" + Q("hpc_batch")
            + "," + Q("seed")       + ":null"
            + "," + Q("compile_pass")    + ":null"
            + "," + Q("structure_score") + ":null"
            + "," + Q("log_path")   + ":" + Q("")
            + "," + Q("timestamp")  + ":" + Q(timestamp)
            + "," + Q("output_code")+ ":" + Q(Esc(outputCode ?? ""))
            + "," + Q("source")     + ":" + Q("batch")
            + "}";

        var targetDir = Path.GetDirectoryName(targetPath);
        if (!string.IsNullOrEmpty(targetDir)) Directory.CreateDirectory(targetDir);
        File.AppendAllText(targetPath, jsonLine + "\n");

        Debug.Log($"Batch run record written: {runId}");
    }

    /// <summary>
    /// Returns true if line contains a "run_id" key matching runId,
    /// tolerating any whitespace around the colon (handles pretty-printed JSON).
    /// </summary>
    static bool LineMatchesRunId(string line, string runId)
        => Regex.IsMatch(line, "\"run_id\"\\s*:\\s*\"" + Regex.Escape(runId) + "\"");

    static string Q(string s) => "\"" + s + "\"";

    static string Esc(string s)
    {
        if (s == null) return "";
        return s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n").Replace("\r", "\\r");
    }
}

} // namespace AICommandLocal
