package com.slg.agentdock.data.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class Iso8601Test {
    @Test
    fun parsesUtcWithMicroseconds() {
        // 2026-11-11T10:20:30.123456Z
        assertEquals(1_794_392_430_123L, parseIsoInstantMillis("2026-11-11T10:20:30.123456Z"))
    }

    @Test
    fun appliesOffsets() {
        assertEquals(
            parseIsoInstantMillis("2026-11-11T10:20:30Z"),
            parseIsoInstantMillis("2026-11-11T17:20:30+07:00"),
        )
        assertEquals(
            parseIsoInstantMillis("2026-11-11T10:20:30Z"),
            parseIsoInstantMillis("2026-11-11T05:50:30-04:30"),
        )
    }

    @Test
    fun handlesEpochAndLeapDay() {
        assertEquals(0L, parseIsoInstantMillis("1970-01-01T00:00:00Z"))
        assertEquals(951_782_400_000L, parseIsoInstantMillis("2000-02-29T00:00:00+00:00"))
    }

    @Test
    fun rejectsMalformedAndOutOfRangeValues() {
        assertNull(parseIsoInstantMillis(""))
        assertNull(parseIsoInstantMillis("yesterday"))
        assertNull(parseIsoInstantMillis("2026-13-01T00:00:00Z"))
        assertNull(parseIsoInstantMillis("2026-02-30T00:00:00Z"))
        assertNull(parseIsoInstantMillis("2026-11-11T24:00:00Z"))
    }
}
