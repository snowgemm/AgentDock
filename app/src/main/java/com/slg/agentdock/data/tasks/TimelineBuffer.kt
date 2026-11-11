package com.slg.agentdock.data.tasks

/**
 * Ordered, de-duplicated view of a task's events. REST catch-up and the live stream
 * can both deliver the same event; the sequence number is the identity, so replays
 * and overlaps are harmless.
 */
class TimelineBuffer(initial: List<TaskEvent> = emptyList()) {
    private val bySequence = java.util.TreeMap<Long, TaskEvent>()

    init {
        initial.forEach { bySequence[it.sequence] = it }
    }

    val lastSequence: Long get() = if (bySequence.isEmpty()) 0L else bySequence.lastKey()

    /** Returns true when at least one previously unseen event was added. */
    fun merge(events: List<TaskEvent>): Boolean {
        var changed = false
        for (event in events) {
            if (event.sequence <= 0 || bySequence.containsKey(event.sequence)) continue
            bySequence[event.sequence] = event
            changed = true
        }
        return changed
    }

    fun snapshot(): List<TaskEvent> = bySequence.values.toList()
}
