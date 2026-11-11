package com.slg.agentdock.data.tasks

import java.util.UUID

/**
 * Gives each user submission one stable idempotency key. Retrying the same content
 * (after a timeout, offline error or app restart of the screen) reuses the key, so
 * the server returns the original task instead of creating a duplicate. Changing the
 * content starts a new submission with a new key; a completed submission is forgotten.
 */
class SubmissionTracker(private val newKey: () -> String = { UUID.randomUUID().toString() }) {
    private data class Pending(val content: String, val key: String)

    private val pending = HashMap<String, Pending>()

    @Synchronized
    fun keyFor(draftId: String, title: String, prompt: String): String {
        val content = "$title\u0000$prompt"
        val existing = pending[draftId]
        if (existing != null && existing.content == content) return existing.key
        return newKey().also { pending[draftId] = Pending(content, it) }
    }

    @Synchronized
    fun complete(draftId: String) {
        pending.remove(draftId)
    }
}

/** Derives a task title from a draft: first non-blank line, bounded, never blank. */
fun deriveTaskTitle(draft: String, fallback: String, maxLength: Int = 80): String {
    val firstLine = draft.lineSequence().map { it.trim() }.firstOrNull { it.isNotEmpty() }.orEmpty()
    val collapsed = firstLine.replace(Regex("\\s+"), " ")
    val bounded = if (collapsed.length <= maxLength) collapsed else collapsed.take(maxLength - 1).trimEnd() + "…"
    return bounded.ifBlank { fallback }
}
