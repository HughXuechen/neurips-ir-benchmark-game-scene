namespace AICommandLocal.OpenAI
{
    public static class Api
    {
        // Default LM Studio local server endpoint (OpenAI-compatible)
        public const string DefaultUrl = "http://127.0.0.1:1234/v1/chat/completions";
    }

    [System.Serializable]
    public struct ResponseMessage
    {
        public string role;
        public string content;
    }

    [System.Serializable]
    public struct ResponseChoice
    {
        public int index;
        public ResponseMessage message;
    }

    [System.Serializable]
    public struct ResponseUsage
    {
        public int prompt_tokens;
        public int completion_tokens;
        public int total_tokens;
    }

    [System.Serializable]
    public struct Response
    {
        public string id;
        public long created;
        public string model;
        public ResponseChoice[] choices;
        public ResponseUsage usage;
    }

    [System.Serializable]
    public struct RequestMessage
    {
        public string role;
        public string content;
    }

    [System.Serializable]
    public struct Request
    {
        public string model;
        public RequestMessage[] messages;
    }
}
