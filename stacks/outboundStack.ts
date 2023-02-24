import * as sst from "@serverless-stack/resources";
import {Stage, Fn, aws_iam as iam, aws_lambda as lambda, aws_ec2 as ec2, Duration, aws_sqs as sqs, aws_kms as kms} from "aws-cdk-lib";
import fs_extra from "fs-extra";
import glob from "glob";
import {Config} from "./config";

export default class OutboundStack extends sst.Stack {

  private prepare_src_path(): string {
    /*
    Create a temp Build-xxx dir as the srcPath for lambdas. Copy only needed application files over there.
    Dependency management files are intentionally left out because we don't want to use SST's bundling mechanism.
     */
    // Remove any previous temp dirs
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
      if (name && srcExclude.indexOf(name) === -1) {
        fs_extra.copySync(`${f}`, `${srcPath}/${name}`)
      }
    });
    return srcPath
  }

  private add_managed_policy(config: Config, role: iam.IRole, idPrefix: string): void {
    /*
    Add additional policies to the given role.
     */
    role.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName("CloudWatchLambdaInsightsExecutionRolePolicy"))
    role.addManagedPolicy(
      iam.ManagedPolicy.fromManagedPolicyArn(this, `${idPrefix}SsmPolicy`,
        Fn.importValue(`${config.platformStackName}-mpolicy-lambda-ssm-lambda-access`)))
    role.addManagedPolicy(
      iam.ManagedPolicy.fromManagedPolicyArn(this, `${idPrefix}XrayPolicy`,
        Fn.importValue(`${config.platformStackName}-mpolicy-lambda-xray`)))
  }

  constructor(scope: sst.App|Stage, id: string, props?: sst.StackProps) {
    // FIXME: OutboundStack could be called directly(i.e. `scope: sst.App`) or via CodePipeline(i.e. `scope: Stage`).
    //  Specifying scope to be a union type is a workaround. Note that we can not call utilities like
    //  `sst.App.setDefaultFunctionProps` without checking scope's type..
    super(scope, id, props);
    console.log("===========================================================================")
    console.log(`tags=${props?.tags}`)
    console.log(`ENVIRONMENT_MODE=${process.env.ENVIRONMENT_MODE}`)
    console.log("===========================================================================")

    const cicdStages = Config.getCicdStageNames()
    let stage: string;
    if (scope instanceof sst.App) {
      stage = scope.stage
      if (cicdStages.indexOf(stage) !== -1) {
        new Error(`Stage ${stage} is reserved for CICD`)
      }
    } else {
      // `scope` is a `Stage` which has no `stage` property.
      // Get `stage` from ENVIRONMENT_MODE set up by CicdStack to be one of cicdStages for CodeBuild.
      // eslint-disable-next-line @typescript-eslint/ban-ts-comment
      // @ts-ignore
      stage = process.env.ENVIRONMENT_MODE
      if (stage || cicdStages.indexOf(stage) === -1) {
        new Error(`Deploying CICD to stage ${stage} is not allowed`)
      }
    }
    const config = Config.getConfig(stage)
    const prefix = `${stage}-tgr-warden-outbound`;

    // NOTE: SST's bundling mechanism for python lambda function can not deal with editable dependencies(i.e.
    // tgr-backend-common). Here is the workaround:
    // 1. Use docker to package dependencies to a layer.
    // 2. Create a build-xxx temp dir as the srcPath that contains only needed application files.
    const layer = new lambda.LayerVersion(this, "Layer", {
      layerVersionName: `${prefix}-layer`,
      code: lambda.Code.fromDockerBuild("src", {
        file: "layer.Dockerfile",
        // See layer.Dockerfile
        imagePath: "/var/dependency",
      }),
    });
    const srcPath = this.prepare_src_path()

    const bus = new sst.EventBus(this, "Bus", {
      cdk: {
        eventBus: {
          eventBusName: `${prefix}-bus`,
        }
      },
    });
    const commonFunctionProps = {
      srcPath,
      layers: [layer],
      vpc: ec2.Vpc.fromLookup(this, "Vpc", {
        vpcName: `${config.networkLayerStackName}-vpc`
      }),
      securityGroups: [
        ec2.SecurityGroup.fromSecurityGroupId(this, "DbSecurityGroup",
          Fn.importValue(`${config.dataLayerStackName}-securitygroup-access-db-id`))
      ],
      vpcSubnets: {
        subnets: [
          ec2.Subnet.fromSubnetId(this, "SubnetA",
            Fn.importValue(`${config.networkLayerStackName}-subnet-app-a-id`)),
          ec2.Subnet.fromSubnetId(this, "SubnetB",
            Fn.importValue(`${config.networkLayerStackName}-subnet-app-b-id`)),
          ec2.Subnet.fromSubnetId(this, "SubnetC",
            Fn.importValue(`${config.networkLayerStackName}-subnet-app-c-id`)),
        ]
      },
    }
    const environment = {
      SENTRY_DSN: config.stageProps.sentryDsn,
      ENVIRONMENT_MODE: config.stageProps.environmentMode,
      ENVIRONMENT_ID: config.stageProps.environmentId,
      DATABASE_PASSWORD_SECRET_KEY: Fn.importValue(
        `${config.dataLayerStackName}-secret-postgres-user-storyfier-arn`),
      DATABASE_NAME: config.stageProps.databaseName,
      DATABASE_USERNAME: config.stageProps.databaseUserName,
      DATABASE_HOST: Fn.importValue(
        `${config.dataLayerStackName}-dbcluster-platform-clusterendpoint-address`),
      LOG_LEVEL: config.stageProps.logLevel,
      OUTBOUND_EVENT_BUS_ARN: bus.eventBusArn,
      OUTBOUND_EVENT_BUS_NAME: bus.eventBusName,
      MAX_RECEIVE_COUNT: "5",
      // https://awslabs.github.io/aws-lambda-powertools-python/
      POWERTOOLS_METRICS_NAMESPACE: "outbound",
      POWERTOOLS_LOGGER_LOG_EVENT: `${config.stageProps.environmentMode !== "prod"}`,
    }

    const commonQueueProps = {
      visibilityTimeout: Duration.seconds(60),
      // https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-configure-sqs-sse-queue.html
      encryption: sqs.QueueEncryption.SQS_MANAGED,
    }

    const transQueue = new sst.Queue(this, "TransQueue", {
      cdk: {
        queue: commonQueueProps,
      },
      consumer: {
        function: {
          functionName: `${prefix}-transformation`,
          handler: "transformation.handler",
          runtime: "python3.8",
          timeout: "20 seconds",
          ...commonFunctionProps,
          environment: {
            ...environment,
            POWERTOOLS_SERVICE_NAME: "transformation",
          },
          // transformation handler should be able to putEvents to the bus.
          permissions: [
            new iam.PolicyStatement({
              actions: ["events:putEvents"],
              effect: iam.Effect.ALLOW,
              resources: [
                bus.eventBusArn,
              ]
            }),
          ],
        },
        cdk: {
          eventSource: {
            reportBatchItemFailures: true,
          }
        },
      },
    });
    // Instead of create a role in commonFunctionPros, we post-add policies to the auto-created role on which sst/cdk
    // sets up some policies for us.
    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
    const transFn = transQueue.consumerFunction!
    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
    this.add_managed_policy(config, transFn.role!, "TransFn")

    const senderQueue = new sst.Queue(this, "SenderQueue", {
      cdk: {
        queue: commonQueueProps,
      },
      consumer: {
        function: {
          functionName: `${prefix}-sender`,
          handler: "sender.handler",
          runtime: "python3.8",
          timeout: "20 seconds",
          ...commonFunctionProps,
          environment: {
            ...environment,
            POWERTOOLS_SERVICE_NAME: "sender",
          },
          // sender handler should be able to publish to the sns.
          permissions: [
            new iam.PolicyStatement({
              actions: ["sns:publish"],
              effect: iam.Effect.ALLOW,
              resources: [
                "*",
              ]
            }),
            new iam.PolicyStatement({
              actions: ["kms:Decrypt"],
              effect: iam.Effect.ALLOW,
              resources: [
                Fn.importValue(`${config.platformStackName}-kms-cloud-credentials-key`),
              ]
            }),
          ],
        },
        cdk: {
          eventSource: {
            reportBatchItemFailures: true,
          }
        },
      },
    });
    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
    const senderFn = senderQueue.consumerFunction!
    // Instead of create a role in commonFunctionPros, we post-add policies to the auto-created role on which sst/cdk
    // sets up some policies for us.
    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
    this.add_managed_policy(config, senderFn.role!, "SenderFn")

    // Topics(SNS) are where the sender sends message to. Usually they sit in the client's cloud.
    // Since Doku are using AliCloud, we manage topics for them.
    // https://docs.aws.amazon.com/sns/latest/dg/sns-enable-encryption-for-topic.html
    const snsMasterKey = kms.Alias.fromAliasName(this, 'SnsKeyAlias', 'aws/sns');
    new sst.Topic(this, "DokuCspmTopic", {
      cdk: {
        topic: {
          masterKey: snsMasterKey,
        }
      }
    })
    new sst.Topic(this, "DokuTdTopic", {
      cdk: {
        topic: {
          masterKey: snsMasterKey,
        }
      }
    })

    bus.addRules(this, {
      transformationRule: {
        cdk: {
          rule: {
            ruleName: `${prefix}-to-transformation`,
            description: "events to be transformed",
            eventPattern: {
              detailType: ["OutboundNotification"],
              detail: {
                // either no route-state or not in the end state(ready_to_send)
                "msg_attrs.route": [{exists: false}, {"anything-but": "ready_to_send"}],
              },
            },
          }
        },
        targets: {
          transQueue
        },
      }
    })
    bus.addRules(this, {
      senderRule: {
        cdk: {
          rule: {
            ruleName: `${prefix}-to-sender`,
            description: "events to be sent",
            eventPattern: {
              detailType: ["OutboundNotification"],
              detail: {
                // the end state(ready_to_send)
                "msg_attrs.route": ["ready_to_send"]
              },
            },
          },
        },
        targets: {
          senderQueue
        },
      }
    });

    // Show the endpoint in the output
    this.addOutputs({
      busArn: {
        value: bus.eventBusArn,
        exportName: `${prefix}-bus-arn`,
      },
      busName: {
        value: bus.eventBusName,
        exportName: `${prefix}-bus-name`,
      }
    });
  }
}
