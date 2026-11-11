package com.slg.agentdock

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.ViewModelProvider
import com.slg.agentdock.ui.AgentDockApp
import com.slg.agentdock.ui.AgentDockViewModel
import com.slg.agentdock.ui.auth.AuthViewModel

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        val app = application as AgentDockApplication
        val repository = app.workspaceRepository
        val auth = app.container.auth
        val viewModel = ViewModelProvider(
            this,
            AgentDockViewModel.Factory(repository),
        )[AgentDockViewModel::class.java]

        val authViewModel = ViewModelProvider(
            this,
            AuthViewModel.Factory(auth?.sessions, auth?.oidc),
        )[AuthViewModel::class.java]

        setContent {
            AgentDockApp(viewModel = viewModel, authViewModel = authViewModel)
        }
    }
}
