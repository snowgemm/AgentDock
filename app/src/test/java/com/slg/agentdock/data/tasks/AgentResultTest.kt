package com.slg.agentdock.data.tasks

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentResultTest {
    private fun event(sequence: Long, type: String, json: String = "{}") = TaskEvent(
        "e$sequence", sequence, type, Json.parseToJsonElement(json) as JsonObject, sequence,
    )

    @Test
    fun noResultEventMeansNoResult() {
        assertNull(extractAgentResult(listOf(event(1, "TASK_CREATED"), event(2, "AGENT_MODEL_CALL"))))
    }

    @Test
    fun verifiedAnswerIsExtractedWithUsage() {
        val result = extractAgentResult(
            listOf(
                event(1, "TASK_CREATED"),
                event(
                    5, "AGENT_RESULT",
                    """{"answer":"4","verified":true,"verification":{"passed":true,"checks":[{"name":"answer_present","passed":true}]},
                        "usage":{"total_tokens":140}}""",
                ),
            ),
        )!!
        assertEquals("4", result.answer)
        assertTrue(result.verified)
        assertTrue(result.failedChecks.isEmpty())
        assertEquals(140L, result.totalTokens)
    }

    @Test
    fun unverifiedAnswerKeepsItsFailedChecksSoTheUiCanSayItIsNotVerified() {
        val result = extractAgentResult(
            listOf(
                event(
                    3, "AGENT_RESULT",
                    """{"answer":"partial","verified":false,"verification":{"passed":false,"checks":
                        [{"name":"not_truncated","passed":false},{"name":"answer_present","passed":true}]}}""",
                ),
            ),
        )!!
        assertFalse(result.verified)
        assertEquals(listOf("not_truncated"), result.failedChecks)
    }

    @Test
    fun missingVerifiedFlagIsTreatedAsNotVerified() {
        val result = extractAgentResult(listOf(event(2, "AGENT_RESULT", """{"answer":"x"}""")))!!
        assertFalse(result.verified)
    }

    @Test
    fun newestResultWins() {
        val result = extractAgentResult(
            listOf(event(2, "AGENT_RESULT", """{"answer":"old","verified":true}"""),
                event(9, "AGENT_RESULT", """{"answer":"new","verified":true}""")),
        )!!
        assertEquals("new", result.answer)
    }
}
