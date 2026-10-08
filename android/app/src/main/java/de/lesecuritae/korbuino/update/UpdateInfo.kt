package de.lesecuritae.korbuino.update

data class UpdateInfo(val tag: String, val version: String, val apkUrl: String, val sha256: String?, val releaseUrl: String?)

internal object UpdateVersions {
    /** Compare dotted numeric versions without treating 0.1.10 as 0.1.2. */
    fun isNewerVersion(remote: String, installed: String): Boolean {
        fun parts(value: String): List<Int> = value.removePrefix("v")
            .split('.', '-', '+')
            .map { it.toIntOrNull() ?: 0 }
            .take(4)
            .let { values -> values + List(4 - values.size) { 0 } }
        return parts(remote).zip(parts(installed)).firstOrNull { (r, i) -> r != i }
            ?.let { (r, i) -> r > i } ?: false
    }
}
