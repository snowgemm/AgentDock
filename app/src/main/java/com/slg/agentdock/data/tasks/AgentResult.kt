package com.slg.agentdock.data.tasks

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull

/** The agent's final answer as recorded in the AGENT_RESULT timeline event. */
data class AgentResult(
    val answer: String,
    /** True only when the server's verifier accepted it; false means "shown, not verified". */
    val verified: Boolean,
    val failedChecks: List<String>,
    val totalTokens: Long?,
)

/**
 * The result lives in the persisted event stream, so it is available after an app
 * restart with nothing cached locally. The newest AGENT_RESULT wins.
 */
fun extractAgentResult(events: List<TaskEvent>): AgentResult? {
    val event = events.lastOrNull { it.type == "AGENT_RESULT" } ?: return null
    val answer = (event.payload["answer"] as? JsonPrimitive)?.contentOrNull ?: return null
    val verified = (event.payload["verified"] as? JsonPrimitive)?.booleanOrNull ?: false
    val checks = (event.payload["verification"] as? JsonObject)?.get("checks") as? JsonArray
    val failed = checks.orEmpty().mapNotNull { element ->
        val check = element as? JsonObject ?: return@mapNotNull null
        val passed = (check["passed"] as? JsonPrimitive)?.booleanOrNull ?: return@mapNotNull null
        if (passed) null else (check["name"] as? JsonPrimitive)?.contentOrNull
    }
    val tokens = ((event.payload["usage"] as? JsonObject)?.get("total_tokens") as? JsonPrimitive)
        ?.contentOrNull?.toLongOrNull()
    return AgentResult(answer, verified, failed, tokens)
}
