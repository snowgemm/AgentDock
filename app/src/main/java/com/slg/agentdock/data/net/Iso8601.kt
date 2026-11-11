package com.slg.agentdock.data.net

private val ISO_INSTANT = Regex(
    """^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|z|[+-]\d{2}(?::?\d{2})?)?$""",
)

/**
 * Parses the ISO-8601 timestamps emitted by the backend into epoch milliseconds.
 *
 * java.time is not available on minSdk 23 without desugaring, so this is a small,
 * dependency-free parser. A timestamp with no offset is treated as UTC. Returns
 * null for anything malformed or out of range instead of guessing.
 */
fun parseIsoInstantMillis(value: String): Long? {
    val match = ISO_INSTANT.matchEntire(value.trim()) ?: return null
    val g = match.groupValues
    val year = g[1].toInt()
    val month = g[2].toInt()
    val day = g[3].toInt()
    val hour = g[4].toInt()
    val minute = g[5].toInt()
    val second = g[6].toInt()
    if (month !in 1..12 || hour !in 0..23 || minute !in 0..59 || second !in 0..59) return null
    if (day !in 1..daysInMonth(year, month)) return null

    val millis = if (g[7].isEmpty()) 0L else g[7].padEnd(3, '0').take(3).toLong()
    val offsetMinutes = parseOffsetMinutes(g[8]) ?: return null
    val epochSeconds = daysFromCivil(year, month, day) * 86_400L +
        hour * 3_600L + minute * 60L + second - offsetMinutes * 60L
    return epochSeconds * 1_000L + millis
}

private fun parseOffsetMinutes(raw: String): Long? {
    if (raw.isEmpty() || raw.equals("Z", ignoreCase = true)) return 0L
    val sign = if (raw[0] == '-') -1L else 1L
    val digits = raw.substring(1).replace(":", "")
    val hours = digits.substring(0, 2).toLong()
    val minutes = if (digits.length >= 4) digits.substring(2, 4).toLong() else 0L
    if (hours > 23 || minutes > 59) return null
    return sign * (hours * 60L + minutes)
}

private fun isLeap(year: Int): Boolean = (year % 4 == 0 && year % 100 != 0) || year % 400 == 0

private fun daysInMonth(year: Int, month: Int): Int = when (month) {
    2 -> if (isLeap(year)) 29 else 28
    4, 6, 9, 11 -> 30
    else -> 31
}

/** Days since 1970-01-01 for a proleptic Gregorian date (Howard Hinnant's algorithm). */
private fun daysFromCivil(year: Int, month: Int, day: Int): Long {
    val y = if (month <= 2) year - 1 else year
    val era = (if (y >= 0) y else y - 399) / 400
    val yearOfEra = y - era * 400
    val shiftedMonth = if (month > 2) month - 3 else month + 9
    val dayOfYear = (153 * shiftedMonth + 2) / 5 + day - 1
    val dayOfEra = yearOfEra * 365 + yearOfEra / 4 - yearOfEra / 100 + dayOfYear
    return era.toLong() * 146_097L + dayOfEra - 719_468L
}
