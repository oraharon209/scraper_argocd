
# Scraper ArgoCD

## Overview

This repository contains a web scraping application for EURO2024 designed to be deployed and managed using ArgoCD. The project is fully integrated with Kubernetes for continuous deployment and management.

## Features

- **Web Scraping**: The application scrapes data from the official EURO 2024 website.
- **ArgoCD Integration**: Manages the deployment and lifecycle of the application within a Kubernetes cluster.
- **Helm Charts**: Used for packaging and deploying the application in Kubernetes.

## Prerequisites

Before you begin, ensure you have met the following requirements:

- Kubernetes cluster up and running.
- ArgoCD installed and configured on your Kubernetes cluster.
- Helm installed on your local machine.
- Docker installed for building images.

## Installation

1. **Clone the repository**:

    ```bash
    git clone https://github.com/oraharon209/scraper_argocd.git
    cd scraper_argocd
    ```

2. **Build the Docker image**:
    - do this step for `backend` `frontend` `live` and `daily`

    ```bash
    docker build -t FOLDER_NAME/REPO_NAME .
    ```

3. **Deploy with ArgoCD**:

   - Ensure your Kubernetes context is set to the desired cluster.
   - Push your Docker image to a container registry accessible by your Kubernetes cluster.
   - Update the Helm chart values in `charts/scraping-app/values.yaml` to point to your Docker image.
   - Deploy the application using ArgoCD.

    ```bash
    argocd app create scraper-app --repo https://github.com/YOUR_REPO/scraper_argocd.git --path charts/scraping-app --dest-server https://kubernetes.default.svc --dest-namespace default
    ```

    - Sync the application:

    ```bash
    argocd app sync scraper-app
    ```

## Usage

Once deployed, the application will start scraping data as defined in your scraping configuration. You can monitor and manage the application via the ArgoCD web interface.
You can also use loki to gather logs.

## Configuration

- **Helm Values**: Customize your deployment by modifying the values in the `values.yaml` file within the Helm chart directory.
- **Environment Variables**: You can set environment variables for the scraper by updating the Helm chart or Dockerfile as needed.
- **Logging**: You can also use Loki to gather and analyze logs from your application. This can be set up by integrating Loki with your Kubernetes cluster via `/loki/loki.yaml`
