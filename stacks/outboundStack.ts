import * as sst from "@serverless-stack/resources";
import {FunctionProps} from "@serverless-stack/resources";
import {Stage} from "aws-cdk-lib";

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

    const bus = new sst.EventBus(this, "Bus");
    const transformationQueue = new sst.Queue(this, "TransformationQueue", {
      consumer: {
        function: {
          functionName: `${prefix}-transformation`,
          srcPath: "src",
          handler: "transformation.handler",
          runtime: "python3.8",
        }
      },
    });
    const senderQueue = new sst.Queue(this, "SenderQueue", {
      consumer: {
        function: {
          functionName: `${prefix}-sender`,
          srcPath: "src",
          handler: "sender.handler",
          runtime: "python3.8",
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
          srcPath: "src",
          handler: "producer.handler",
          runtime: "python3.8",
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
