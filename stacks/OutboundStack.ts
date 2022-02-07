import * as sst from "@serverless-stack/resources";
import {FunctionProps} from "@serverless-stack/resources";


export default class OutboundStack extends sst.Stack {
  constructor(scope: sst.App, id: string, props?: sst.StackProps) {
    super(scope, id, props);
    const prefix = `${scope.stage}-tgr-warden-outbound`
    const bus = new sst.EventBus(this, "Bus");
    const transformationQueue = new sst.Queue(this, "TransformationQueue", {
      consumer: {
        function: {
          functionName: `${prefix}-transformation`,
          srcPath: "src",
          handler: "transformation.handler",
        }
      },
    });
    const senderQueue = new sst.Queue(this, "SenderQueue", {
      consumer: {
        function: {
          functionName: `${prefix}-sender`,
          srcPath: "src",
          handler: "sender.handler",
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
            // either no route-state or in the end state(ready-to-send)
            "route-state": [{exists: false}, {"anything-but": "ready-to-send"}]
          },
        },
        targets: [transformationQueue]
      }
    })
    bus.addRules(this, {
      senderRule: {
        ruleName: `${prefix}-to-sender`,
        description: "events to be sent",
        eventPattern: {
          detailType: ["outboundNotification"],
          detail: {
            // either no route-state or in the end state(ready-to-send)
            "route-state": ["ready-to-send"]
          },
        },
        targets: [senderQueue]
      }
    })


    // Temporarily create an HTTP API for testing
    const api = new sst.Api(this, "Api", {
      routes: {
        "GET /": {
          srcPath: "src",
          handler: "producer.handler",
          environment: {
            OUTBOUND_EVENT_BUS_ARN: bus.eventBusArn,
            OUTBOUND_EVENT_BUS_NAME: bus.eventBusName,
          },
        },
      }
      //routes: {
      //  "GET /": "producer.handler",
      //},
    });

    // Show the endpoint in the output
    this.addOutputs({
      "ApiEndpoint": api.url,
      "BusArn": bus.eventBusArn,
      "BusName": bus.eventBusName,
    });
  }
}
