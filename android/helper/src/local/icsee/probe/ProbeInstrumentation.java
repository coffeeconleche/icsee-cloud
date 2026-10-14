package local.icsee.probe;

import android.app.Application;
import android.app.Instrumentation;
import android.os.Bundle;
import android.os.Message;
import org.json.JSONObject;
import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.atomic.AtomicBoolean;

/** Only native login and video-saving entry points; no visual renderer. */
public final class ProbeInstrumentation extends Instrumentation {
    private Class<?> sdk;
    private JSONObject cfg;
    private File dir;
    private PrintWriter log;
    private OutputStream raw;
    private ServerSocket server;
    private Socket socket;
    private final ArrayBlockingQueue<byte[]> socketQueue = new ArrayBlockingQueue<byte[]>(128);
    private final AtomicBoolean socketFailed = new AtomicBoolean(false);
    private volatile boolean socketWriterRunning;
    private Thread socketWriter;
    private final CountDownLatch finished = new CountDownLatch(1);
    private Object callback;
    private int handler;
    private int media;
    private boolean videoStarted;
    private long rawBytes;
    private long rawFrames;
    private long skippedAudioFrames;
    private long audioFrames;
    private long skippedMetadataFrames;
    private long normalizedIFrames;
    private long normalizedPFrames;
    private long unknownVideoPrefixes;

    private boolean rawMode() { String mode = cfg.optString("mode"); return "raw".equals(mode) || "socket".equals(mode); }

    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }

    private synchronized void status(String event) {
        if (log != null) { log.println(System.currentTimeMillis() + " " + event); log.flush(); }
    }

    private void failure(String stage, Throwable throwable) {
        Throwable cause = throwable instanceof InvocationTargetException ? ((InvocationTargetException) throwable).getTargetException() : throwable;
        status("failure stage=" + stage + " type=" + cause.getClass().getName());
        for (StackTraceElement frame : cause.getStackTrace()) {
            status("frame=" + frame.getClassName() + "." + frame.getMethodName() + ":" + frame.getLineNumber());
        }
    }

    private Object call(String name, Class<?>[] types, Object... values) throws Exception {
        Object result = sdk.getMethod(name, types).invoke(null, values);
        status("sdk=" + name + " result=" + (result instanceof Number || result instanceof Boolean ? result.toString() : "completed"));
        return result;
    }

    @Override public void onStart() {
        try {
            dir = getTargetContext().getFilesDir();
            log = new PrintWriter(new FileOutputStream(new File(dir, "status.log"), false), true);
            byte[] configBytes;
            try (InputStream in = new FileInputStream(new File(dir, "request.json")); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[4096]; int n;
                while ((n = in.read(buffer)) != -1) out.write(buffer, 0, n);
                configBytes = out.toByteArray();
            }
            cfg = new JSONObject(new String(configBytes, StandardCharsets.UTF_8));
            java.util.Arrays.fill(configBytes, (byte)0);
            status("private-request-removed=" + new File(dir,"request.json").delete());
            status("probe-start mode=" + ("socket".equals(cfg.optString("mode")) ? "socket" : rawMode() ? "raw" : "save"));
            System.setOut(new PrintStream(new OutputStream() { public void write(int b) {} }));
            System.setErr(new PrintStream(new OutputStream() { public void write(int b) {} }));
            if ("socket".equals(cfg.optString("mode"))) {
                int port = cfg.optInt("socketPort",23100);
                if (port < 1 || port > 65535) throw new IllegalArgumentException();
                server = new ServerSocket();
                server.setReuseAddress(true);
                server.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"),port));
                server.setSoTimeout(30000);
                status("socket-listening=true");
                socket = server.accept();
                socket.setTcpNoDelay(true);
                raw = socket.getOutputStream();
                server.close();
                startSocketWriter();
                status("socket-client-connected=true");
            }
            runOnMainSync(new Runnable() { @Override public void run() {
                try { initialize(); } catch (Throwable t) { failure("initialize", t); finished.countDown(); }
            }});
            int seconds = Math.max(5, Math.min(86400, cfg.optInt("timeoutSeconds", 60)));
            finished.await(seconds, TimeUnit.SECONDS);
            runOnMainSync(new Runnable() { @Override public void run() {
                try { if (media > 0) call(rawMode() ? "DevCloseReturnRealStream" : "DevCloseRealTimeStream", new Class<?>[]{int.class}, media); }
                catch (Throwable t) { failure("stop", t); }
            }});
            stopSocketWriter();
            if (raw != null) raw.close();
            status("probe-finish started=" + videoStarted + " rawBytes=" + rawBytes + " rawFrames=" + rawFrames + " normalizedIFrames=" + normalizedIFrames + " normalizedPFrames=" + normalizedPFrames + " unknownVideoPrefixes=" + unknownVideoPrefixes + " skippedAudioFrames=" + skippedAudioFrames + " skippedMetadataFrames=" + skippedMetadataFrames + " savedBytes=" + new File(dir, "camera.h264").length());
        } catch (Throwable t) { failure("run", t); }
        finally {
            stopSocketWriter();
            try { if (raw != null) raw.close(); } catch (IOException ignored) {}
            try { if (socket != null) socket.close(); } catch (IOException ignored) {}
            try { if (server != null) server.close(); } catch (IOException ignored) {}
            if (log != null) log.close(); Bundle result = new Bundle(); result.putString("status", "local probe completed; inspect private files"); finish(0, result);
        }
    }

    private void initialize() throws Exception {
        sdk = Class.forName("com.lib.FunSDK");
        status("native-libraries-loaded=" + sdk.getField("isLoadLibrarySuccess").getBoolean(null));
        call("SetApplication", new Class<?>[]{Application.class}, (Application)getTargetContext().getApplicationContext());
        Class<?> initClass = Class.forName("com.lib.sdk.struct.SInitParam");
        Object init = initClass.getConstructor().newInstance();
        initClass.getField("st_0_nAppType").setInt(init, 5);
        byte[] source = (byte[])initClass.getField("st_1_nSource").get(init);
        Class.forName("com.basic.G").getMethod("SetValue",byte[].class,String.class).invoke(null,source,"xmshop");
        byte[] initBytes = (byte[])Class.forName("com.basic.G").getMethod("ObjToBytes", Object.class).invoke(null, init);
        call("Init", new Class<?>[]{int.class, byte[].class}, 0, initBytes);
        call("SysInitNet", new Class<?>[]{String.class, int.class}, dir.getAbsolutePath(), 0);
        call("SysInitUserAgentInfo",new Class<?>[]{String.class},"Android_iCSee_7.9.4_G_local-probe");
        call("XMCloundPlatformInit", new Class<?>[]{String.class, String.class, String.class, int.class}, cfg.getString("uuid"), cfg.getString("appKey"), cfg.getString("appSecret"), cfg.getInt("movedCard"));
        call("SysSetServerIPPort", new Class<?>[]{String.class,String.class,int.class}, "MI_SERVER",cfg.optString("miServer","https://sa-ams.jftechws.com"),443);
        call("SysSetServerIPPort", new Class<?>[]{String.class,String.class,int.class}, "CAPS_SERVER",cfg.optString("capsServer","https://caps-sa.jftechws.com"),443);
        call("SetFunIntAttr", new Class<?>[]{int.class,int.class},45,169);
        call("SetFunIntAttr", new Class<?>[]{int.class,int.class},44,1);
        call("SetFunIntAttr", new Class<?>[]{int.class,int.class},22,1);
        call("SetFunIntAttr", new Class<?>[]{int.class,int.class},26,1);
        call("SetP2PDataEncryptEnable",new Class<?>[]{int.class},1);
        Class<?> iface = Class.forName("com.lib.IFunSDKResult");
        callback = Proxy.newProxyInstance(iface.getClassLoader(),new Class<?>[]{iface}, new InvocationHandler() {
            @Override public Object invoke(Object proxy, Method method, Object[] args) {
                if ("hashCode".equals(method.getName())) return System.identityHashCode(proxy);
                if ("equals".equals(method.getName())) return proxy == args[0];
                if ("toString".equals(method.getName())) return "LocalVideoProbeCallback";
                if ("OnFunSDKResult".equals(method.getName())) {
                    try { onCallback((Message)args[0],args[1]); } catch (Throwable t) { failure("callback",t); }
                    return 0;
                }
                return null;
            }
        });
        handler = (Integer)call("GetId",new Class<?>[]{int.class,iface},0,callback);
        call("SysGetDevList",new Class<?>[]{int.class,String.class,String.class,int.class},handler,cfg.getString("username"),cfg.getString("password"),0);
    }

    private void onCallback(Message message, Object content) throws Exception {
        byte[] bytes = (byte[])content.getClass().getField("pData").get(content);
        int length = bytes == null ? 0 : bytes.length;
        int arg3 = content.getClass().getField("arg3").getInt(content);
        boolean rawCallback = message.what == 5533 && raw != null && length > 0;
        boolean rawFrame = rawCallback && message.arg2 == 1;
        boolean audioFrame = rawCallback && message.arg2 == 2 && cfg.optBoolean("includeAudio", false);
        if (rawCallback && message.arg2 == 2 && !audioFrame) skippedAudioFrames++;
        if (audioFrame) audioFrames++;
        if (rawCallback && message.arg2 == 3) skippedMetadataFrames++;
        byte[] video = rawFrame ? videoPayload(bytes) : null;
        if (rawFrame) rawFrames++;
        if (!rawCallback || (rawFrame && (rawFrames <= 5 || rawFrames % 120 == 0))) {
            status("callback id=" + message.what + " result=" + message.arg1 + " arg2=" + message.arg2 + " arg3=" + arg3 + " bytes=" + length + (rawFrame ? " videoBytes=" + video.length + " frame=" + rawFrames + " " + classify(video) : ""));
        }
        if (message.what == 5000 && message.arg1 >= 0 && !videoStarted) {
            videoStarted = true;
            String token = (String)sdk.getMethod("DevGetLocalEncToken",String.class).invoke(null,cfg.getString("serial"));
            status("cached-enc-token-length=" + (token == null ? 0 : token.length()));
            int channel = cfg.optInt("channel",0), stream = cfg.optInt("stream",1);
            if (rawMode()) {
                if (!"socket".equals(cfg.optString("mode"))) raw = new FileOutputStream(new File(dir,"camera.raw"));
                media = (Integer)call("DevReturnRealStream",new Class<?>[]{int.class,String.class,int.class,int.class,int.class},handler,cfg.getString("serial"),channel,stream,0);
            } else {
                media = (Integer)call("DevSaveRealTimeStream",new Class<?>[]{int.class,String.class,int.class,int.class,String.class,int.class},handler,cfg.getString("serial"),channel,stream,new File(dir,"camera.h264").getAbsolutePath(),0);
            }
        }
        if (rawFrame || audioFrame) {
            if ("socket".equals(cfg.optString("mode"))) {
                byte[] payload = video;
                if (cfg.optBoolean("includeAudio", false)) {
                    ByteBuffer frame = ByteBuffer.allocate(20 + bytes.length).order(ByteOrder.BIG_ENDIAN);
                    frame.putInt(0x49434156).put((byte)(audioFrame ? 2 : 1));
                    frame.put(new byte[3]).putInt(bytes.length).putLong(android.os.SystemClock.elapsedRealtime());
                    frame.put(bytes); payload = frame.array();
                }
                if (!socketFailed.get() && !socketQueue.offer(payload)) failSocket("queue-overflow");
            } else {
                try { raw.write(video); raw.flush(); rawBytes += video.length; }
                catch (IOException disconnected) { status("video-consumer-disconnected=true"); finished.countDown(); }
            }
        }
    }

    private void startSocketWriter() {
        socketWriterRunning = true;
        socketWriter = new Thread(new Runnable() { @Override public void run() {
            while (socketWriterRunning) {
                try {
                    byte[] frame = socketQueue.take();
                    if (!socketWriterRunning) break;
                    raw.write(frame);
                    raw.flush();
                    rawBytes += frame.length;
                } catch (InterruptedException stopped) { break; }
                catch (IOException disconnected) { if (socketWriterRunning) failSocket("consumer-disconnected"); break; }
            }
        }}, "LocalVideoSocketWriter");
        socketWriter.start();
    }

    private void failSocket(String reason) {
        if (socketFailed.compareAndSet(false,true)) {
            status("video-socket-failed=" + reason);
            finished.countDown();
        }
    }

    private void stopSocketWriter() {
        socketWriterRunning = false;
        try { if (socket != null) socket.close(); } catch (IOException ignored) {}
        if (socketWriter != null) {
            socketWriter.interrupt();
            try { socketWriter.join(1000); } catch (InterruptedException stopped) { Thread.currentThread().interrupt(); }
        }
        socketQueue.clear();
    }

    /** Normalize only the two Sofia headers directly verified in this camera's callbacks. */
    private byte[] videoPayload(byte[] bytes) {
        if (bytes.length >= 4 && bytes[0] == 0 && bytes[1] == 0 && bytes[2] == 1) {
            int marker = bytes[3] & 255;
            if (marker == 252 && bytes.length >= 16) { normalizedIFrames++; return java.util.Arrays.copyOfRange(bytes,16,bytes.length); }
            if (marker == 253 && bytes.length >= 8) { normalizedPFrames++; return java.util.Arrays.copyOfRange(bytes,8,bytes.length); }
        }
        unknownVideoPrefixes++;
        return bytes;
    }

    private static String classify(byte[] bytes) {
        for (int i = 0; i + 5 < bytes.length && i < 64; i++) {
            int header = -1;
            if (bytes[i] == 0 && bytes[i + 1] == 0 && bytes[i + 2] == 1) header = i + 3;
            else if (bytes[i] == 0 && bytes[i + 1] == 0 && bytes[i + 2] == 0 && bytes[i + 3] == 1) header = i + 4;
            if (header >= 0) {
                int avc = bytes[header] & 31;
                int hevc = (bytes[header] >>> 1) & 63;
                return "annexB=true avcNal=" + avc + " hevcNal=" + hevc;
            }
        }
        return "annexB=false";
    }
}
