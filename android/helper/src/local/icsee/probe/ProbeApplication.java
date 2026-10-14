package local.icsee.probe;

import android.app.Application;

/** Deliberately does not start the vendor application's UI, ads, or services. */
public final class ProbeApplication extends Application {
    @Override public void onCreate() { super.onCreate(); }
}
