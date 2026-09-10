plugins { id("com.android.application") }

dependencies {
    implementation("com.google.android.gms:play-services-mlkit-text-recognition:19.0.1")
}

android {
    namespace = "com.afaaqtuwaiq.naqliat"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.afaaqtuwaiq.naqliat"
        minSdk = 23
        targetSdk = 35
        versionCode = 5
        versionName = "0.1.4"
    }
    signingConfigs {
        getByName("debug") {
            enableV1Signing = true
            enableV2Signing = true
            enableV3Signing = true
            enableV4Signing = true
        }
    }
    buildTypes { getByName("debug") { signingConfig = signingConfigs.getByName("debug") } }
}
