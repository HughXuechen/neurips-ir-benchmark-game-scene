using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using System;
using System.IO;
using System.Reflection;
using System.Text.RegularExpressions;

namespace AICommandLocal {

public sealed class AICommandWindow : EditorWindow
{
    #region Temporary script file operations

    internal const string TempFilePath = "Assets/AICommandLocalTemp.cs";
    const string LogFolderPath = "Assets/AICommandLocalLogs";

    bool TempFileExists => File.Exists(TempFilePath);

    // Store current log file path for appending execution results
    static string _currentLogFilePath;

    // EditorPrefs key for persisting runId across assembly reloads
    const string RunIdPrefKey = "AICommandLocal_LastRunId";
    const string PatternIdPrefKey = "AICommandLocal_LastPatternId";
    const string MethodPrefKey = "AICommandLocal_LastMethod";
    const string ModelPrefKey = "AICommandLocal_LastModel";

    static string GetTimestamp() => DateTime.Now.ToString("yyyyMMdd_HHmmss");

    static string GetSlug(string prompt)
    {
        if (string.IsNullOrEmpty(prompt)) return "empty";
        // Take first 20 chars, replace non-alphanumeric with underscore
        var slug = prompt.Length > 20 ? prompt.Substring(0, 20) : prompt;
        slug = Regex.Replace(slug, @"[^a-zA-Z0-9]", "_");
        slug = Regex.Replace(slug, @"_+", "_").Trim('_');
        return string.IsNullOrEmpty(slug) ? "task" : slug;
    }

    static void EnsureLogFolder()
    {
        if (!Directory.Exists(LogFolderPath))
        {
            Directory.CreateDirectory(LogFolderPath);
            AssetDatabase.Refresh();
        }
    }

    static string SaveRunLog(string timestamp, string prompt, string rawResponse, string cleanCode)
    {
        EnsureLogFolder();

        var settings = AICommandSettings.instance;
        var slug = GetSlug(prompt);
        var logFileName = $"{timestamp}_{slug}.log";
        var logFilePath = Path.Combine(LogFolderPath, logFileName);

        var logContent = $@"================================================================================
AI COMMAND LOCAL - RUN LOG
================================================================================

TIMESTAMP:      {timestamp}
MODEL:          {settings.modelName}
API BASE URL:   {settings.apiBaseUrl}
TEMP FILE:      {TempFilePath}

--------------------------------------------------------------------------------
PROMPT
--------------------------------------------------------------------------------
{prompt}

--------------------------------------------------------------------------------
RAW LLM RESPONSE
--------------------------------------------------------------------------------
{rawResponse ?? "(null)"}

--------------------------------------------------------------------------------
CLEANED CODE (after fence stripping)
--------------------------------------------------------------------------------
{cleanCode ?? "(null)"}

--------------------------------------------------------------------------------
EXECUTION RESULT
--------------------------------------------------------------------------------
";

        File.WriteAllText(logFilePath, logContent);
        Debug.Log($"AI Command log saved to: {logFilePath}");

        return logFilePath;
    }

    static void AppendToLog(string message)
    {
        if (!string.IsNullOrEmpty(_currentLogFilePath) && File.Exists(_currentLogFilePath))
        {
            File.AppendAllText(_currentLogFilePath, message + "\n");
        }
    }

    static void DeletePreviousTempScript()
    {
        // Delete previous temp script to avoid compile conflicts
        if (File.Exists(TempFilePath))
        {
            AssetDatabase.DeleteAsset(TempFilePath);
        }
    }

    void CreateScriptAsset(string code)
    {
        // UnityEditor internal method: ProjectWindowUtil.CreateScriptAssetWithContent
        var flags = BindingFlags.Static | BindingFlags.NonPublic;
        var method = typeof(ProjectWindowUtil).GetMethod("CreateScriptAssetWithContent", flags);
        method.Invoke(null, new object[]{TempFilePath, code});
    }

    #endregion

    #region Script generator

    static string WrapPrompt(string input)
      => "Write a Unity Editor script.\n" +
         " - It provides its functionality as a menu item placed \"Edit\" > \"Do Task\".\n" +
         " - Do NOT create any EditorWindow or GUI.\n" +
         " - Do NOT use OnGUI, GUILayout, or EditorWindow.GetWindow.\n" +
         " - Execute the task immediately inside the menu command.\n" +
         " - Don't use GameObject.FindGameObjectsWithTag.\n" +
         " - Prefer creating new objects directly when the task asks to create objects.\n" +
         " - Do NOT clone existing objects. Always create new primitives when asked to create objects.\n" +
         " - Do NOT search for existing objects at all (no Find*, no name/tag lookups). Do NOT use Instantiate. Use GameObject.CreatePrimitive or new GameObject only.\n" +
         " - Output ONLY raw C# code. Do NOT include markdown fences (no ```csharp or ```).\n" +
         " - I only need the script body. Don't add any explanation.\n" +
         "The task is described as follows:\n" + input;

    static string StripMarkdownFences(string code)
    {
        if (string.IsNullOrEmpty(code)) return code;

        // Remove leading ```csharp, ```cs, or ``` (with optional language identifier)
        code = Regex.Replace(code, @"^\s*```(?:csharp|cs)?\s*\n?", "", RegexOptions.IgnoreCase);

        // Remove trailing ```
        code = Regex.Replace(code, @"\n?\s*```\s*$", "");

        return code.Trim();
    }

    static bool HasForbiddenPatterns(string code)
    {
        if (string.IsNullOrEmpty(code)) return false;
        return code.Contains("FindObjectsOfType")
            || code.Contains("Instantiate(")
            || code.Contains("GameObject.Find")
            || code.Contains("FindGameObjectsWithTag");
    }

    void RunGenerator()
    {
        // Generate runId early and log a marker for compile_pass detection
        var runId = System.DateTime.Now.ToString("yyyyMMdd_HHmmss_fff");
        Debug.Log($"AICommandRunStart:{runId}");

        var chatResult = OpenAIUtil.InvokeChatWithResult(WrapPrompt(_prompt));
        if (!chatResult.success)
        {
            EditorUtility.DisplayDialog("AI Command Error",
                "Failed to generate code. Check the Console for details.\n\n" +
                "Make sure LM Studio is running at: " + AICommandSettings.instance.apiBaseUrl,
                "OK");
            return;
        }

        var rawResponse = chatResult.content;

        // Strip markdown code fences if present
        var cleanCode = StripMarkdownFences(rawResponse);
        if (HasForbiddenPatterns(cleanCode))
        {
            var stricterPrompt =
                _prompt
                + "\n\nIMPORTANT: Do NOT search for existing objects. "
                + "Do NOT use Find* or Instantiate. "
                + "Always create new primitives via GameObject.CreatePrimitive or new GameObject.";
            var retryResult = OpenAIUtil.InvokeChatWithResult(WrapPrompt(stricterPrompt));
            if (retryResult.success)
            {
                chatResult = retryResult;
                rawResponse = chatResult.content;
                cleanCode = StripMarkdownFences(rawResponse);
            }
        }

        // Generate timestamp for logging
        var timestamp = GetTimestamp();

        // Save single log file with all info
        _currentLogFilePath = SaveRunLog(timestamp, _prompt, rawResponse, cleanCode);

        // Write structured JSONL record + raw response JSON
        try
        {
            var method = RunLogger.ExtractMethod(_prompt);
            RunLogger.LogRun(chatResult, _prompt, _currentLogFilePath, runId, method);
            EditorPrefs.SetString(RunIdPrefKey, runId);
            EditorPrefs.SetString(PatternIdPrefKey, RunLogger.ExtractPatternId(_prompt));
            EditorPrefs.SetString(MethodPrefKey, method);
            EditorPrefs.SetString(ModelPrefKey, AICommandSettings.instance.modelName);
        }
        catch (System.Exception ex)
        {
            Debug.LogWarning($"RunLogger failed (non-fatal): {ex.Message}");
        }

        // Delete previous temp script before creating new one (avoid compile conflicts)
        DeletePreviousTempScript();

        Debug.Log("AI command script:" + cleanCode);
        CreateScriptAsset(cleanCode);

        // Register fallback compile_pass check for when compilation fails
        // (OnAfterAssemblyReload won't fire on compile errors)
        ScheduleCompilePassFallback(runId);
    }

    static void ScheduleCompilePassFallback(string runId)
    {
        const double checkDelaySec = 2.0;
        const double timeoutSec = 30.0;
        var startTime = EditorApplication.timeSinceStartup;

        void FallbackCheck()
        {
            var elapsed = EditorApplication.timeSinceStartup - startTime;

            // If OnAfterAssemblyReload already cleared the pref, we're done
            if (EditorPrefs.GetString(RunIdPrefKey, "") != runId)
            {
                EditorApplication.update -= FallbackCheck;
                return;
            }

            // Wait at least checkDelaySec before first attempt
            if (elapsed < checkDelaySec) return;

            var compilePass = RunLogger.DetectCompilePass(runId);
            if (compilePass >= 0)
            {
                var method = EditorPrefs.GetString(MethodPrefKey, "no_schema");
                var patternId = EditorPrefs.GetString(PatternIdPrefKey, "");
                var model = EditorPrefs.GetString(ModelPrefKey, "");
                if (compilePass == 1 && !string.IsNullOrEmpty(runId))
                {
                    ExportGeneratedScene(runId, patternId, method, model);
                }
                RunLogger.UpdateCompilePass(runId, compilePass, method);
                EditorPrefs.DeleteKey(RunIdPrefKey);
                EditorApplication.update -= FallbackCheck;
                return;
            }

            // Give up after timeout (marker may not have been flushed)
            if (elapsed > timeoutSec)
            {
                EditorApplication.update -= FallbackCheck;
            }
        }

        EditorApplication.update += FallbackCheck;
    }

    #endregion

    #region Editor GUI

    string _prompt = "Create 4 cubes at random points.";

    const string ConnectionInfoText =
      "Using LM Studio at: {0}\nModel: {1}\n\n" +
      "Configure in Edit > Project Settings > AI Command (Local)";

    bool IsServerConfigured
      => !string.IsNullOrEmpty(AICommandSettings.instance.apiBaseUrl);

    [MenuItem("Window/AI Command (Local)")]
    static void Init() => GetWindow<AICommandWindow>(true, "AI Command (Local)");

    void OnGUI()
    {
        var settings = AICommandSettings.instance;

        // Show connection info
        EditorGUILayout.HelpBox(
            string.Format(ConnectionInfoText, settings.apiBaseUrl, settings.modelName),
            MessageType.Info);

        EditorGUILayout.Space();

        if (IsServerConfigured)
        {
            if (GUILayout.Button("Run", GUILayout.Height(28))) RunGenerator();
            EditorGUILayout.Space();
            _prompt = EditorGUILayout.TextArea(_prompt, GUILayout.ExpandHeight(true));
        }
        else
        {
            EditorGUILayout.HelpBox(
                "API Base URL not configured. Please set it in Project Settings.",
                MessageType.Error);
        }
    }

    #endregion

    #region Scene export (M2 data generation)

    /// <summary>
    /// Saves the current active scene to results/unity_generated/{model}/{pattern}/{method}/{runId}/scene.unity
    /// so that parse_generated_scene.py can produce gen_parsed.json / gen_links.json.
    /// </summary>
    static void ExportGeneratedScene(string runId, string patternId, string method, string model)
    {
        if (string.IsNullOrEmpty(runId) || patternId == "_debug")
            return;

        try
        {
            var modelDir = string.IsNullOrEmpty(model) ? "unknown_model" : model;
            var outDir = Path.Combine(
                RunLogger.ProjectRoot,
                "results", "unity_generated", modelDir, patternId, method, runId);
            Directory.CreateDirectory(outDir);

            var scenePath = Path.Combine(outDir, "scene.unity");
            var activeScene = EditorSceneManager.GetActiveScene();
            EditorSceneManager.SaveScene(activeScene, scenePath, true);
            Debug.Log($"Generated scene exported to: {scenePath}");
        }
        catch (Exception ex)
        {
            Debug.LogWarning($"Scene export failed (non-fatal): {ex.Message}");
        }
    }

    #endregion

    #region Script lifecycle

    void OnEnable()
      => AssemblyReloadEvents.afterAssemblyReload += OnAfterAssemblyReload;

    void OnDisable()
      => AssemblyReloadEvents.afterAssemblyReload -= OnAfterAssemblyReload;

    void OnAfterAssemblyReload()
    {
        if (!TempFileExists) return;
        var pendingRunId = EditorPrefs.GetString(RunIdPrefKey, "");
        if (!string.IsNullOrEmpty(pendingRunId))
        {
            var scheduledKey = "AICommandLocal_Scheduled_" + pendingRunId;
            if (SessionState.GetBool(scheduledKey, false))
                return;
            SessionState.SetBool(scheduledKey, true);
        }
        EditorApplication.delayCall += ExecuteAfterReload;
    }

    internal static void ExecuteAfterReload()
    {
        var pendingRunId = EditorPrefs.GetString(RunIdPrefKey, "");
        var pendingPatternId = EditorPrefs.GetString(PatternIdPrefKey, "");
        var pendingMethod = EditorPrefs.GetString(MethodPrefKey, "no_schema");
        var pendingModel = EditorPrefs.GetString(ModelPrefKey, "");
        bool executionSucceeded = false;

        // Prevent double execution when both window instance and reload hook fire.
        if (!string.IsNullOrEmpty(pendingRunId))
        {
            var executedKey = "AICommandLocal_Executed_" + pendingRunId;
            if (SessionState.GetBool(executedKey, false))
                return;
            SessionState.SetBool(executedKey, true);
        }

        // Execute the generated menu command with error handling
        try
        {
            var menuExists = EditorApplication.ExecuteMenuItem("Edit/Do Task");
            if (menuExists)
            {
                AppendToLog("Status: SUCCESS\nMenu item 'Edit/Do Task' executed successfully.");
                executionSucceeded = true;
            }
            else
            {
                AppendToLog("Status: COMPILE_FAIL\nMenu item 'Edit/Do Task' not found (compile error).");
            }
        }
        catch (Exception ex)
        {
            var errorMsg = $"Status: FAILED\n" +
                          $"Exception: {ex.GetType().Name}\n" +
                          $"Message: {ex.Message}\n" +
                          $"Stack Trace:\n{ex.StackTrace}";

            AppendToLog(errorMsg);

            Debug.LogError($"AI Command: Failed to execute generated script.\n" +
                          $"Exception: {ex.GetType().Name}: {ex.Message}\n" +
                          $"Stack trace: {ex.StackTrace}\n" +
                          $"Check the temp file at: {TempFilePath}");
        }

        // Export generated scene for M2 evaluation
        if (executionSucceeded && !string.IsNullOrEmpty(pendingRunId))
        {
            ExportGeneratedScene(pendingRunId, pendingPatternId, pendingMethod, pendingModel);
        }

        // Patch compile_pass in JSONL using marker-based Editor.log scan
        if (!string.IsNullOrEmpty(pendingRunId))
        {
            try
            {
                var compilePass = RunLogger.DetectCompilePass(pendingRunId);
                if (compilePass >= 0)
                    RunLogger.UpdateCompilePass(pendingRunId, compilePass, pendingMethod);
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"compile_pass update failed (non-fatal): {ex.Message}");
            }
            EditorPrefs.DeleteKey(RunIdPrefKey);
            EditorPrefs.DeleteKey(PatternIdPrefKey);
            EditorPrefs.DeleteKey(MethodPrefKey);
            EditorPrefs.DeleteKey(ModelPrefKey);
            SessionState.EraseBool("AICommandLocal_Scheduled_" + pendingRunId);
            SessionState.EraseBool("AICommandLocal_Executed_" + pendingRunId);
        }

        // NOTE: Temp file (Assets/AICommandLocalTemp.cs) is kept for debugging.
        // Check Assets/AICommandLocalLogs/*.log for run details.
    }

    #endregion
}

// Ensure reload handling runs even if the window isn't open.
[InitializeOnLoad]
static class AICommandReloadHook
{
    static AICommandReloadHook()
    {
        AssemblyReloadEvents.afterAssemblyReload += ExecuteIfTempExists;
    }

    static void ExecuteIfTempExists()
    {
        if (!File.Exists(AICommandWindow.TempFilePath)) return;
        var pendingRunId = EditorPrefs.GetString("AICommandLocal_LastRunId", "");
        if (!string.IsNullOrEmpty(pendingRunId))
        {
            var scheduledKey = "AICommandLocal_Scheduled_" + pendingRunId;
            if (SessionState.GetBool(scheduledKey, false))
                return;
            SessionState.SetBool(scheduledKey, true);
        }
        EditorApplication.delayCall += AICommandWindow.ExecuteAfterReload;
    }
}

} // namespace AICommandLocal
