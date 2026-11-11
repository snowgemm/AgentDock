package com.slg.agentdock.ui.screens

import android.text.format.DateUtils
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.slg.agentdock.R
import com.slg.agentdock.data.tasks.Approval
import com.slg.agentdock.data.tasks.ApprovalRisk

/**
 * Shows exactly what the agent wants to do and asks for an explicit decision on THAT
 * action: tool, target, key arguments, risk, expected effect and expiry. The digest
 * shown here is what the server will bind the approval to.
 */
@Composable
fun ApprovalCard(
    approval: Approval,
    deciding: Boolean,
    onApprove: () -> Unit,
    onDeny: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(12.dp),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.tertiary),
        modifier = modifier.fillMaxWidth().testTag("approval.card"),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Text(
                text = stringResource(R.string.approval_heading),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.height(10.dp))
            DetailRow(stringResource(R.string.approval_effect), approval.summary, "approval.effect")
            DetailRow(stringResource(R.string.approval_tool), approval.tool, "approval.tool")
            DetailRow(stringResource(R.string.approval_target), approval.target, "approval.target")
            DetailRow(stringResource(R.string.approval_risk), stringResource(approval.risk.labelRes()), "approval.risk")
            approval.keyArgs.forEach { (name, value) ->
                DetailRow(name, value, "approval.arg.$name")
            }
            DetailRow(
                stringResource(R.string.approval_expires),
                DateUtils.getRelativeTimeSpanString(
                    approval.expiresAtMs, System.currentTimeMillis(), DateUtils.MINUTE_IN_MILLIS,
                ).toString(),
                "approval.expires",
            )
            DetailRow(stringResource(R.string.approval_action_id), approval.digest.take(12), "approval.digest")
            Spacer(Modifier.height(6.dp))
            Text(
                text = stringResource(R.string.approval_scope_note),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
                OutlinedButton(
                    onClick = onDeny,
                    enabled = !deciding,
                    modifier = Modifier.weight(1f).testTag("approval.deny"),
                ) { Text(stringResource(R.string.approval_deny)) }
                Button(
                    onClick = onApprove,
                    enabled = !deciding,
                    modifier = Modifier.weight(1f).testTag("approval.approve"),
                ) { Text(stringResource(R.string.approval_approve)) }
            }
        }
    }
}

@Composable
private fun DetailRow(label: String, value: String, tag: String) {
    Column(modifier = Modifier.padding(bottom = 6.dp).testTag(tag)) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(text = value, style = MaterialTheme.typography.bodyMedium)
    }
}

private fun ApprovalRisk.labelRes(): Int = when (this) {
    ApprovalRisk.READ_ONLY -> R.string.risk_read_only
    ApprovalRisk.REVERSIBLE -> R.string.risk_reversible
    ApprovalRisk.CONSEQUENTIAL -> R.string.risk_consequential
    ApprovalRisk.UNKNOWN -> R.string.risk_unknown
}
