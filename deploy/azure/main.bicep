// Workforce Identity & Lifecycle Analytics on Azure Container Apps, sized to stay inside the free grant.
//
//   console (external HTTPS, your IP only) ──► api (internal only) ──► Neon PostgreSQL (outside Azure)
//
// Both apps scale to zero when idle and to at most one replica, at the smallest size (0.25 vCPU, 0.5 GiB).
// Secrets are Container Apps secrets, passed as secure parameters by scripts/azure_deploy.py; they
// never appear in this file, the deployment outputs or the deployment history.

@description('Prefix for resource names.')
param name string = 'workforce'

param location string = resourceGroup().location

@description('Container image, e.g. ghcr.io/<owner>/workforce-identity:<commit sha>.')
param image string

@description('GitHub user that owns the image.')
param registryUsername string

@secure()
@description('GitHub token with read:packages only, used to pull the private image.')
param registryPassword string

@secure()
@description('SQLAlchemy URL of the Neon database (postgresql+psycopg://...?sslmode=require).')
param databaseUrl string

@secure()
param groqApiKey string = ''

@secure()
param geminiApiKey string = ''

@description('The only address allowed to open the console, e.g. 203.0.113.7/32.')
param allowedCidr string

// Optional AI keys: only create the secret and the variable when a key is given.
var aiSecrets = concat(
  empty(groqApiKey) ? [] : [{ name: 'groq-api-key', value: groqApiKey }],
  empty(geminiApiKey) ? [] : [{ name: 'gemini-api-key', value: geminiApiKey }]
)
var aiEnv = concat(
  empty(groqApiKey) ? [] : [{ name: 'GROQ_API_KEY', secretRef: 'groq-api-key' }],
  empty(geminiApiKey) ? [] : [{ name: 'GEMINI_API_KEY', secretRef: 'gemini-api-key' }]
)
var registry = {
  server: 'ghcr.io'
  username: registryUsername
  passwordSecretRef: 'registry-password'
}
var smallest = {
  cpu: json('0.25')
  memory: '0.5Gi'
}
var scaleToZero = {
  minReplicas: 0
  maxReplicas: 1
}

// Log Analytics: 5 GB a month is free. The daily cap keeps ingestion well under that.
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${name}-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: json('0.1') }
  }
}

// Consumption-only environment: no VNet, no workload profiles, so only per-second app usage is billed,
// and the monthly free grant covers that.
resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${name}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

// The API has internal ingress only: it is reachable from the console, not from the internet.
resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${name}-api'
  location: location
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      ingress: {
        external: false
        targetPort: 8000
        transport: 'auto'
      }
      registries: [registry]
      secrets: concat([
        { name: 'registry-password', value: registryPassword }
        { name: 'database-url', value: databaseUrl }
      ], aiSecrets)
    }
    template: {
      containers: [
        {
          name: 'api'
          image: image
          resources: smallest
          env: concat([
            { name: 'DATABASE_URL', secretRef: 'database-url' }
            { name: 'LOG_LEVEL', value: 'INFO' }
          ], aiEnv)
        }
      ]
      scale: scaleToZero
    }
  }
}

// The console is the only public endpoint: HTTPS from Container Apps, open to one IP address.
// It gets the API's internal address and nothing else; no database URL, no API keys.
resource console 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${name}-console'
  location: location
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8501
        transport: 'auto'
        ipSecurityRestrictions: [
          { name: 'owner', action: 'Allow', ipAddressRange: allowedCidr }
        ]
      }
      registries: [registry]
      secrets: [
        { name: 'registry-password', value: registryPassword }
      ]
    }
    template: {
      containers: [
        {
          name: 'console'
          image: image
          command: ['streamlit', 'run', 'streamlit_app/app.py', '--server.address=0.0.0.0', '--server.port=8501']
          resources: smallest
          env: [
            { name: 'API_BASE_URL', value: 'https://${api.properties.configuration.ingress.fqdn}' }
          ]
        }
      ]
      scale: scaleToZero
    }
  }
}

output consoleUrl string = 'https://${console.properties.configuration.ingress.fqdn}'
output apiInternalUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output logWorkspace string = logs.name
