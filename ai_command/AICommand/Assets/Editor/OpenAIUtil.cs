using UnityEngine;
using UnityEditor;
using UnityEngine.Networking;
using System.Text;

namespace AICommandLocal {

public struct ChatResult
{
    public string content;
    public string rawJson;
    public long latencyMs;
    public OpenAI.Response parsedResponse;
    public bool success;
}

static class OpenAIUtil
{
    static string CreateChatRequestBody(string prompt, string modelName)
    {
        var msg = new OpenAI.RequestMessage();
        msg.role = "user";
        msg.content = prompt;

        var req = new OpenAI.Request();
        req.model = modelName;
        req.messages = new [] { msg };

        return JsonUtility.ToJson(req);
    }

    public static ChatResult InvokeChatWithResult(string prompt)
    {
        var result = new ChatResult();
        var settings = AICommandSettings.instance;

        var requestBody = CreateChatRequestBody(prompt, settings.modelName);

        var post = new UnityWebRequest(settings.apiBaseUrl, "POST");
        var bodyRaw = Encoding.UTF8.GetBytes(requestBody);
        post.uploadHandler = new UploadHandlerRaw(bodyRaw);
        post.downloadHandler = new DownloadHandlerBuffer();
        post.SetRequestHeader("Content-Type", "application/json");

        try
        {
            if (settings.timeout > 0)
                post.timeout = settings.timeout;

            if (!string.IsNullOrEmpty(settings.apiKey))
                post.SetRequestHeader("Authorization", "Bearer " + settings.apiKey);

            var sw = System.Diagnostics.Stopwatch.StartNew();
            var req = post.SendWebRequest();

            for (var progress = 0.0f; !req.isDone; progress += 0.01f)
            {
                EditorUtility.DisplayProgressBar
                  ("AI Command (Local)", "Generating with " + settings.modelName + "...", progress);
                System.Threading.Thread.Sleep(100);
                progress += 0.01f;
            }
            EditorUtility.ClearProgressBar();
            sw.Stop();
            result.latencyMs = sw.ElapsedMilliseconds;

            if (post.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError($"AI Command request failed: {post.error}\nResponse: {post.downloadHandler.text}");
                result.rawJson = post.downloadHandler.text;
                return result;
            }

            result.rawJson = post.downloadHandler.text;
            result.parsedResponse = JsonUtility.FromJson<OpenAI.Response>(result.rawJson);

            if (result.parsedResponse.choices == null || result.parsedResponse.choices.Length == 0)
            {
                Debug.LogError($"AI Command: No choices in response.\nResponse: {result.rawJson}");
                return result;
            }

            result.content = result.parsedResponse.choices[0].message.content;
            result.success = true;
            return result;
        }
        finally
        {
            post.Dispose();
        }
    }

    // Keep backward-compatible method
    public static string InvokeChat(string prompt)
    {
        var result = InvokeChatWithResult(prompt);
        return result.success ? result.content : null;
    }
}

} // namespace AICommandLocal
