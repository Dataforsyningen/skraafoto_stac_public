# stac-api 📚🗄️

## skraafotodistribution-stac-api

SDFE implementation of STAC API.

Original:

MIT License
Copyright (c) 2020 Arturo AI

---

**Documentation**: [https://stac-utils.github.io/stac-fastapi/](https://stac-utils.github.io/stac-fastapi/)

**Source Code**: [https://github.com/stac-utils/stac-fastapi](https://github.com/stac-utils/stac-fastapi)

---

## Configuration
The application is configured using environment variables. These may be put in a file `/.env` like
```.env
WEB_CONCURRENCY=10
DEBUG=TRUE
POSTGRES_USER=my_user
POSTGRES_PASS=my_password
POSTGRES_DBNAME=database_name
POSTGRES_HOST=database_host
POSTGRES_PORT=5432
POSTGRES_APPLICATION_NAME=my_debug_application
# Base path of the proxying tile server
COGTILER_BASEPATH=https://skraafotodistribution-tile-api.k8s-test-121.septima.dk/cogtiler
```

## Development

### Running with docker compose

To run it simply add your configuration in an `.env` file as described above and use:
`docker compose up`

Now you can look at the api at http://localhost:8081/.

### Debugging with docker

Using vscode install the [Docker](https://marketplace.visualstudio.com/items?itemName=ms-azuretools.vscode-docker) extension.

Then create

`.vscode/launch.json`:
```json
{
    // Use IntelliSense to learn about possible attributes.
    // Hover to view descriptions of existing attributes.
    // For more information, visit: https://go.microsoft.com/fwlink/?linkid=830387
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Docker: Python - Fastapi",
            "type": "docker",
            "request": "launch",
            "preLaunchTask": "docker-run: debug",
            "python": {
                "pathMappings": [
                    {
                        "localRoot": "${workspaceFolder}/src/stac_fastapi",
                        "remoteRoot": "/app/stac_fastapi"
                    }
                ],
                "projectType": "fastapi"
            }
        }
    ]
}
```

and `.vscode/tasks.json` (note that app configuration cannot be read from the `.env` file here and needs to be repeated):
```json
{
	"version": "2.0.0",
	"tasks": [
		{
			"type": "docker-build",
			"label": "docker-build",
			"platform": "python",
			"dockerBuild": {
				"tag": "skraafoto_stac_public:latest",
				"dockerfile": "${workspaceFolder}/Dockerfile_dev",
				"context": "${workspaceFolder}",
				"pull": true
			}
		},
		{
			"type": "docker-run",
			"label": "docker-run: debug",
			"dependsOn": [
				"docker-build"
			],
			"dockerRun": {
				"ports": [
					{
						"containerPort": 8081,
						"hostPort": 8081
					}
				],
        "env": {
					"APP_PORT": "8081",
					"DEBUG": "TRUE",
					"ENVIRONMENT": "local",
					"POSTGRES_USER": "my_db_user",
					"POSTGRES_PASS": "my_db_password",
					"POSTGRES_DBNAME": "db_name",
					"POSTGRES_HOST": "db_host",
					"POSTGRES_PORT": "db_port",
					"POSTGRES_APPLICATION_NAME": "stac_fastapi_vscode_debugging",
					"WEB_CONCURRENCY": "1",
					"COGTILER_BASEPATH": "https://skraafotodistribution-tile-api.k8s-test-121.septima.dk/cogtiler"
				}
			},
			"python": {
				"args": [
					"stac_fastapi.sqlalchemy.app:app",
					"--host",
					"0.0.0.0",
					"--port",
					"8081",
					"--reload"
				],
				"module": "uvicorn"
			}
		}
	]
}
```

Now you should be able to hit "Start debugging" `Docker: Python - Fastapi` which will launch the APU in a docker cointainer supporting breakpoints in your code.

### Testing

Pytest requires the modules to be installed in editable mode. To do this correctly, we use Anaconda.

`conda create --name skraafoto-stac-api python=3.9`

On my machine it was also needed to run:

`conda bash init`

To make sure that conda grabs the right python interpreter. Now activate the environment:

`conda activate skraafoto-stac-api`

And install the packages in this order:

```
  pip install wheel && \
  pip install -e "./src/stac_fastapi/api[dev]" && \
  pip install -e "./src/stac_fastapi/types[dev]" && \
  pip install -e "./src/stac_fastapi/extensions[dev]"
```

Now install the SQLalchemy implementation:

`pip install -e "./src/stac_fastapi/sqlalchemy[dev,server]"`

And finally you should be able to run `pytest src` on the commandline, and have VScode discover the tests using the `testing` icon in the left-hand toolbar ( it looks like a chemestry vial). Make sure VScode has the proper python interpreter configured. It can be set typing `CTRL + P` -> `Python: Select interpreter` and then finding the new interpreter. If you can't find it, you need to reload VSCode.
