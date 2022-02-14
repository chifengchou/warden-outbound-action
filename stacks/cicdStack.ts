import * as sst from "@serverless-stack/resources";
import {CodeBuildStep, CodePipeline, CodePipelineSource } from "aws-cdk-lib/pipelines";
import {Effect, PolicyStatement} from "aws-cdk-lib/aws-iam";
import {Stage, StageProps} from "aws-cdk-lib";
import OutboundStack from "./outboundStack";
import {Config} from "./config";


export default class CicdStack extends sst.Stack {
  constructor(scope: sst.App, id: string, props?: sst.StackProps) {
    super(scope, id, props);

    const cicdStages = Config.getCicdStageNames()
    if (scope.stage || cicdStages.indexOf(scope.stage) === -1) {
      new Error(`Deploying CICD to stage ${scope.stage} is not allowed`)
    }
    const config = Config.getConfig(scope.stage)
    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
    const gitProps = config.gitProps!
    const prefix = `${scope.stage}-tgr-warden-outbound`;

    const input = CodePipelineSource.connection(
      `${gitProps.githubOwner}/${gitProps.githubRepo}`,
      `${gitProps.gitBranch}`,
      {
        connectionArn: gitProps.githubConnectionArn,
        // allow submodule
        codeBuildCloneOutput: true,
      }
    );
    const rolePolicyStatements = [
      new PolicyStatement({
        actions: ["secretsmanager:GetSecretValue"],
        effect: Effect.ALLOW,
        resources: [
          `arn:aws:secretsmanager:${scope.region}:${scope.account}:secret:${gitProps.githubSecretName}*`
        ],
      }),
      new PolicyStatement({
        actions: ["ssm:GetParameter"],
        effect: Effect.ALLOW,
        resources: ["*"],
      }),
      new PolicyStatement({
        actions: ["ec2:Describe*"],
        effect: Effect.ALLOW,
        resources: ["*"],
      }),
      // Workaround this error in CodeBuild, which leads to failing to publish assets:
      // > current credentials could not be used to assume 'arn:aws:iam::410801124909:role/cdk-hnb659fds-deploy-role-410801124909-ap-southeast-1'
      new PolicyStatement({
        actions: ["sts:AssumeRole"],
        effect: Effect.ALLOW,
        resources: [`arn:aws:iam::${scope.account}:role/cdk-hnb659fds-*`],
      }),
    ];
    const synth = new CodeBuildStep("Build", {
      projectName: `${prefix}-build`,
      input,
      env: {
        ENVIRONMENT_ID: config.stageProps.environmentId,
        ENVIRONMENT_MODE: config.stageProps.environmentMode,
      },
      installCommands: [
        // Retrieving submodules
        "mkdir -p /root/.ssh/",
        "touch /root/.ssh/known_hosts",
        "ssh-keyscan github.com >> /root/.ssh/known_hosts",
        `aws secretsmanager get-secret-value --secret-id ${gitProps.githubSecretName} | jq -r .SecretString > /root/.ssh/temp_rsa`,
        "chmod 400 /root/.ssh/temp_rsa",
        'eval "$(ssh-agent -s)" && ssh-add /root/.ssh/temp_rsa',
        "git submodule update --init --recursive",
        // Testing
        // Building
        "npm install",
      ],
      commands: [
        `npx sst build --stage ${scope.stage}`
      ],
      primaryOutputDirectory: ".build/cdk.out",
      rolePolicyStatements,
    });
    const pipeline = new CodePipeline(this, "Pipeline", {
      pipelineName: `${prefix}-pipeline`,
      synth,
      dockerEnabledForSynth: true,
      crossAccountKeys: false,
    });
    pipeline.addStage(new OutboundStage(this, "Stage"));
  }
}


class OutboundStage extends Stage {
  constructor(scope: sst.Stack, id: string, props?: StageProps) {
    super(scope, id, props);
    // FIXME: We pass in a Stage(`this`) where sst.App is required. This is a workaround because the lack of support of
    //  using sst.App in CodePipeline. See the implementation of OutboundStack.
    new OutboundStack(this, "Stack", {
      stackName: `${scope.stage}-tgr-warden-outbound-stack`
    });
  }
}