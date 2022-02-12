import * as sst from "@serverless-stack/resources";
import {Stage, aws_lambda, StageProps} from "aws-cdk-lib";
import fs_extra from "fs-extra";
import glob from "glob";

export default class OutboundStack extends sst.Stack {
  // FIXME: OutboundStack could be called locally or via CodePipeline. The `scope` could be sst.App or Stage,
  //  respectively. This is a workaround as sst.App can't be directly added to CodePipeline as a Stage. Note that we
  //  can not call utilities like `sst.App.setDefaultFunctionProps` because of this workaround.
  constructor(scope: sst.App|Stage, id: string, props?: sst.StackProps) {
    super(scope, id, props);

    let prefix: string;
    if (scope instanceof sst.App) {
      prefix = `${scope.stage}-tgr-warden-outbound`;
    } else {
      prefix = `${process.env.ENVIRONMENT_MODE}-tgr-warden-outbound`;
    }

    // NOTE: sst's bundling mechanism for python lambda function can not deal with editable dependencies(i.e.
    // tgr-backend-common). Here is the workaround:
    // 1. Use docker to package dependencies to a layer.
    // 2. Create a build-xxx temp dir as the srcPath for sst to package lambdas. Copy src/*(without $excludeSrc) over.
    const layer = new aws_lambda.LayerVersion(this, "Layer", {
      layerVersionName: `${prefix}-layer`,
      code: aws_lambda.Code.fromDockerBuild("src", {
        file: "layer.Dockerfile",
        // See layer.Dockerfile
        imagePath: "/var/dependency",
      }),
    });
    // Remove the previous temp dir
    glob.sync("build-*").forEach(d => {
      fs_extra.removeSync(d)
    });
    const srcPath = fs_extra.mkdtempSync("build-");
    // We will use glob pattern to list files under src. By default, hidden files are ignored and only the first level
    // files/directories are listed. We further exclude the result:
    const srcExclude = [
      // dependencies are handled in layer instead
      "Pipfile", "Pipfile.lock", "requirements.txt", "poetry.lock", "pyproject.toml",
      "tgr-backend-common",
      // others
      "__pycache__",
    ]
    glob.sync("src/*").forEach(f => {
      const name = f.split("/")[1]
      if (typeof name !== "undefined" && srcExclude.indexOf(name) === -1) {
        fs_extra.copySync(`${f}`, `${srcPath}/${name}`)
      }
    });

    const bus = new sst.EventBus(this, "Bus");
    const transformationQueue = new sst.Queue(this, "TransformationQueue", {
      consumer: {
        function: {
          functionName: `${prefix}-transformation`,
          srcPath,
          handler: "transformation.handler",
          runtime: "python3.8",
          layers: [layer],
        }
      },
    });
    const senderQueue = new sst.Queue(this, "SenderQueue", {
      consumer: {
        function: {
          functionName: `${prefix}-sender`,
          srcPath,
          handler: "sender.handler",
          runtime: "python3.8",
          layers: [layer],
        }
      }
    });

    bus.addRules(this, {
      transformationRule: {
        ruleName: `${prefix}-to-transformation`,
        description: "events to be transformed",
        eventPattern: {
          detailType: ["outboundNotification"],
          detail: {
            // either no route-state or not in the end state(ready-to-send)
            "route-state": [{exists: false}, {"anything-but": "ready-to-send"}]
          },
        },
        targets: [transformationQueue]
      }
    });
    bus.addRules(this, {
      senderRule: {
        ruleName: `${prefix}-to-sender`,
        description: "events to be sent",
        eventPattern: {
          detailType: ["outboundNotification"],
          detail: {
            // the end state(ready-to-send)
            "route-state": ["ready-to-send"]
          },
        },
        targets: [senderQueue]
      }
    });

    // Temporarily create an HTTP API for testing
    const api = new sst.Api(this, "Api", {
      routes: {
        "GET /": {
          functionName: `${prefix}-producer`,
          srcPath,
          handler: "producer.handler",
          runtime: "python3.8",
          layers: [layer],
          environment: {
            OUTBOUND_EVENT_BUS_ARN: bus.eventBusArn,
            OUTBOUND_EVENT_BUS_NAME: bus.eventBusName,
          },
        },
      }
    });

    // Show the endpoint in the output
    this.addOutputs({
      "ApiEndpoint": api.url,
      "BusArn": bus.eventBusArn,
      "BusName": bus.eventBusName,
    });
  }
}
