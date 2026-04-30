apiVersion: apps/v1
kind: Deployment
metadata:
  name: annotation-api
spec:
  template:
    spec:
      containers:
        - name: annotation-api
          resources:
            requests:
              cpu: ${API_CPU_REQUEST}
              memory: ${API_MEMORY_REQUEST}
            limits:
              cpu: "${API_CPU_LIMIT}"
              memory: ${API_MEMORY_LIMIT}
