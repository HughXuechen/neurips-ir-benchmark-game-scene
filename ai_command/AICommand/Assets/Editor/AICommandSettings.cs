using UnityEngine;
using UnityEditor;

namespace AICommandLocal {

[FilePath("UserSettings/AICommandLocalSettings.asset",
          FilePathAttribute.Location.ProjectFolder)]
public sealed class AICommandSettings : ScriptableSingleton<AICommandSettings>
{
    // LM Studio base URL (OpenAI-compatible endpoint)
    public string apiBaseUrl = "http://127.0.0.1:1234/v1/chat/completions";

    // Model name for LM Studio
    public string modelName = "deepseek-coder-v2-lite-instruct";

    // Optional API key (LM Studio typically doesn't require one)
    public string apiKey = "";

    // Request timeout in seconds (0 = no timeout)
    public int timeout = 0;

    public void Save() => Save(true);
    void OnDisable() => Save();
}

sealed class AICommandSettingsProvider : SettingsProvider
{
    public AICommandSettingsProvider()
      : base("Project/AI Command (Local)", SettingsScope.Project) {}

    public override void OnGUI(string search)
    {
        var settings = AICommandSettings.instance;

        var baseUrl = settings.apiBaseUrl;
        var modelName = settings.modelName;
        var key = settings.apiKey;
        var timeout = settings.timeout;

        EditorGUI.BeginChangeCheck();

        EditorGUILayout.LabelField("LM Studio Configuration", EditorStyles.boldLabel);
        baseUrl = EditorGUILayout.TextField("API Base URL", baseUrl);
        modelName = EditorGUILayout.TextField("Model Name", modelName);

        EditorGUILayout.Space();
        EditorGUILayout.LabelField("Optional Settings", EditorStyles.boldLabel);
        key = EditorGUILayout.TextField("API Key (optional)", key);
        timeout = EditorGUILayout.IntField("Timeout (seconds)", timeout);

        if (EditorGUI.EndChangeCheck())
        {
            settings.apiBaseUrl = baseUrl;
            settings.modelName = modelName;
            settings.apiKey = key;
            settings.timeout = timeout;
            settings.Save();
        }
    }

    [SettingsProvider]
    public static SettingsProvider CreateCustomSettingsProvider()
      => new AICommandSettingsProvider();
}

} // namespace AICommandLocal
