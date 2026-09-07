package com.daipihsy.geminiimagetool;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;

public class ProtocolTest {
    @Test public void normalizesProtocolRoots() {
        assertEquals("https://generativelanguage.googleapis.com/v1beta", Protocol.baseUrl("", Protocol.GEMINI));
        assertEquals("https://api.openai.com/v1", Protocol.baseUrl("", Protocol.OPENAI_IMAGES));
        assertEquals("https://relay.example/proxy/v1beta", Protocol.baseUrl("https://relay.example/proxy/v1/", Protocol.GEMINI));
        assertEquals("https://relay.example/proxy/v1", Protocol.baseUrl("https://relay.example/proxy/v1beta/", Protocol.OPENAI_CHAT));
        assertEquals(Protocol.OPENAI_IMAGES, Protocol.normalizeProtocol("openai"));
    }
    @Test public void rejectsUnsafeOrCompleteEndpoints() {
        for (String url : new String[]{"http://relay.example", "https://u:p@relay.example", "https://relay.example?key=x", "https://relay.example/v1/images/generations"})
            assertThrows(IllegalArgumentException.class, () -> Protocol.baseUrl(url, Protocol.OPENAI_IMAGES));
    }
    @Test public void rejectsModelPathInjection() {
        assertEquals(Protocol.BANANA, Protocol.modelId("models/" + Protocol.BANANA));
        for (String value : new String[]{"../models", "model?key=x", "", "https://evil.example", "a\nheader"})
            assertThrows(IllegalArgumentException.class, () -> Protocol.modelId(value));
    }
    @Test public void preservesReferenceOrderAndSeed() throws Exception {
        JSONArray refs = new JSONArray().put(new JSONObject().put("inlineData", new JSONObject().put("data", "first")))
            .put(new JSONObject().put("inlineData", new JSONObject().put("data", "second")));
        JSONObject body = Protocol.geminiBody(Protocol.BANANA, "prompt", "1:1", "4K", 123L, false, false, refs);
        JSONArray parts = body.getJSONArray("contents").getJSONObject(0).getJSONArray("parts");
        assertEquals("first", parts.getJSONObject(1).getJSONObject("inlineData").getString("data"));
        assertEquals("second", parts.getJSONObject(2).getJSONObject("inlineData").getString("data"));
        assertEquals(123L, body.getJSONObject("generationConfig").getLong("seed"));
        assertFalse(body.has("tools"));
    }
    @Test public void omitsAutoRatioAndRandomSeed() throws Exception {
        JSONObject config = Protocol.geminiBody(Protocol.BANANA, "x", "自适应", "1K", null, false, false, new JSONArray()).getJSONObject("generationConfig");
        assertFalse(config.has("seed")); assertFalse(config.getJSONObject("imageConfig").has("aspectRatio"));
    }
    @Test public void restrictsImageSearchAndHandlesFallback() throws Exception {
        JSONObject flash = Protocol.geminiBody(Protocol.BANANA, "x", "1:1", "1K", null, true, true, new JSONArray());
        assertTrue(flash.getJSONArray("tools").getJSONObject(0).getJSONObject("googleSearch").getJSONObject("searchTypes").has("imageSearch"));
        JSONObject pro = Protocol.geminiBody(Protocol.PRO, "x", "4:5", "512", null, true, true, new JSONArray());
        assertFalse(pro.getJSONArray("tools").getJSONObject(0).getJSONObject("googleSearch").has("searchTypes"));
        JSONObject image = pro.getJSONObject("generationConfig").getJSONObject("imageConfig");
        assertEquals("3:4", image.getString("aspectRatio")); assertEquals("1K", image.getString("imageSize"));
    }
    @Test public void matchesDesktopGptSizeTable() throws Exception {
        JSONObject body = Protocol.openAiBody(Protocol.GPT, "x", "9:16", "4K");
        assertEquals("2160x3840", body.getString("size")); assertEquals(1, body.getInt("n"));
        assertFalse(body.has("seed")); assertFalse(body.has("response_format"));
        assertFalse(Protocol.openAiBody("gpt-image-1", "x", "自适应", "1K").has("size"));
        assertThrows(IllegalArgumentException.class, () -> Protocol.openAiSize(Protocol.GPT, "4:1", "2K"));
    }
    @Test public void buildsChatImageRequestWithOrderedReferences() throws Exception {
        JSONObject body = Protocol.openAiChatBody("relay-image-model", "draw", "1:1", "2K", new JSONArray().put("data:image/png;base64,one").put("data:image/png;base64,two"));
        JSONArray content = body.getJSONArray("messages").getJSONObject(0).getJSONArray("content");
        assertTrue(content.getJSONObject(0).getString("text").startsWith("draw"));
        assertEquals("data:image/png;base64,one", content.getJSONObject(1).getJSONObject("image_url").getString("url"));
        assertEquals("image", body.getJSONArray("modalities").getString(1));
    }
    @Test public void parsesOpenAiAndChatImageShapes() throws Exception {
        assertEquals("abc", Protocol.openAiImage(new JSONObject("{\"data\":[{\"b64_json\":\"abc\"}]}")));
        assertEquals("data:image/png;base64,xyz", Protocol.openAiImage(new JSONObject("{\"choices\":[{\"message\":{\"images\":[{\"image_url\":{\"url\":\"data:image/png;base64,xyz\"}}]}}]}")));
        assertEquals("https://cdn.example/a.png", Protocol.openAiImage(new JSONObject("{\"choices\":[{\"message\":{\"content\":\"![image](https://cdn.example/a.png)\"}}]}")));
    }
    @Test public void skipsThoughtImages() throws Exception {
        JSONObject payload = new JSONObject("{\"candidates\":[{\"content\":{\"parts\":[{\"thought\":true,\"inlineData\":{\"data\":\"draft\"}},{\"inlineData\":{\"data\":\"final\"}}]}}]}");
        assertEquals("final", Protocol.geminiImage(payload).getString("data"));
    }
    @Test public void redactsApiKeysAndRawHtml() {
        String error = Protocol.friendlyError(401, "{\"error\":{\"message\":\"bad secret-demo-key\"}}", "secret-demo-key");
        assertFalse(error.contains("secret-demo-key")); assertTrue(error.contains("已隐藏密钥"));
        assertFalse(Protocol.friendlyError(502, "<html>private server details</html>", "").contains("private"));
    }
}
