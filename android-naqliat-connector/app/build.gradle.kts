plugins { id("com.android.application") }

dependencies {
    implementation("com.google.mlkit:text-recognition:16.0.1")
}

android {
    namespace = "com.afaaqtuwaiq.naqliat"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.afaaqtuwaiq.naqliat"
        minSdk = 23
        targetSdk = 35
        versionCode = 2
        versionName = "0.1.1"
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
