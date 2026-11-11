package com.slg.agentdock.data.tasks

/**
 * Remembers, per task, the highest event sequence the user has seen. Only the number
 * is persisted (never event content); it marks what is new when a task is reopened
 * after the process was restarted. Timeline history itself always comes from the server.
 */
interface LastSeenStore {
    suspend fun get(taskId: String): Long
    suspend fun put(taskId: String, sequence: Long)
}
