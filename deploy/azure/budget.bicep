// Email alert if the subscription spends anything. Deployed at subscription scope, separately from the
// app, so it stays in place when the app's resource group is deleted.
targetScope = 'subscription'

param name string = 'workforce'

@description('Where the alerts go. Passed at deploy time; not stored in the repository.')
param alertEmail string

@description('Budgets start on the first day of a month.')
param startDate string = utcNow('yyyy-MM-01')

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
  name: '${name}-any-spend'
  properties: {
    category: 'Cost'
    amount: 1
    timeGrain: 'Monthly'
    timePeriod: { startDate: startDate }
    notifications: {
      actualOverOneCent: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 1 // percent of $1
        thresholdType: 'Actual'
        contactEmails: [alertEmail]
      }
      forecastOverOneDollar: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 100
        thresholdType: 'Forecasted'
        contactEmails: [alertEmail]
      }
    }
  }
}
