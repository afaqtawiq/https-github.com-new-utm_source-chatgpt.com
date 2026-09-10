# Afaaq Naqliat Connector

Android companion for capturing load details that the user visibly opens in the official Naqliat Driver app (`com.naqliat.carrier`). It is limited by Android configuration to that package and posts normalized load data to `/api/v7/naqliat/loads`.

The connector does not automate login, read credentials, bypass controls, book loads, or contact load owners. A user must open the load details screen. Configure `NAQLIAT_CONNECTOR_TOKEN` on the server and enter the same token locally in the connector settings.
