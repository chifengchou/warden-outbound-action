import * as sst from "@serverless-stack/resources";
import {CodeBuildStep, CodePipeline, CodePipelineSource, ShellStep} from "aws-cdk-lib/pipelines";
import {Effect, PolicyStatement} from "aws-cdk-lib/aws-iam";
import {Stage, StageProps} from "aws-cdk-lib";
import OutboundStack from "./outboundStack";

export const cicdStages = ["dev", "staging", "prod"]

interface GitConnectionConfig {
  github_owner: string
  github_repo: string
  git_branch: string
  github_connection_arn: string
  github_secret_name: string
}

interface StageConfig {
  environment_id: string
}

const cicdConfig: Record<string, GitConnectionConfig & StageConfig> = {
  dev: {
    github_owner: "horangi-ir",
    github_repo: "tgr-warden-outbound",
    //git_branch: "develop",
    git_branch: "feature/cicd",
    github_connection_arn: "arn:aws:codestar-connections:ap-southeast-1:410801124909:connection/a6f85a35-6448-48ba-ad25-46bc9bb8caeb",
    github_secret_name: "tgr-dev-1-platform-github-ssh",
    environment_id: "1",
  },
  staging: {
    github_owner: "horangi-ir",
    github_repo: "tgr-warden-outbound",
    git_branch: "release/candidate",
    github_connection_arn: "",
    github_secret_name: "tgr-dev-1-platform-github-ssh",
    environment_id: "1",
  },
  prod: {
    github_owner: "horangi-ir",
    github_repo: "tgr-warden-outbound",
    git_branch: "master",
    github_connection_arn: "arn:aws:codestar-connections:ap-southeast-1:410801124909:connection/a6f85a35-6448-48ba-ad25-46bc9bb8caeb",
    github_secret_name: "tgr-dev-1-platform-github-ssh",
    environment_id: "0",
  },
};


export default class CicdStack extends sst.Stack {
  constructor(scope: sst.App, id: string, props?: sst.StackProps) {
    super(scope, id, props);

    const prefix = `${scope.stage}-tgr-warden-outbound`;
    const config = cicdConfig[scope.stage]
    const input = CodePipelineSource.connection(
      `${config.github_owner}/${config.github_repo}`,
      `${config.git_branch}`,
      {
        connectionArn: config.github_connection_arn,
      }
    );
    const rolePolicyStatements = [
      new PolicyStatement({
        actions: ["secretsmanager:GetSecretValue"],
        effect: Effect.ALLOW,
        resources: [
          `arn:aws:secretsmanager:${scope.region}:${scope.account}:secret:${config.github_secret_name}*`
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
        ENVIRONMENT_ID: config.environment_id,
        ENVIRONMENT_MODE: scope.stage
      },
      installCommands: [
        // Retrieving submodules
        //"mkdir -p /root/.ssh/",
        //"touch /root/.ssh/known_hosts",
        //"ssh-keyscan github.com >> /root/.ssh/known_hosts",
        //`aws secretsmanager get-secret-value --secret-id ${config.github_secret_name} | jq -r ".SecretString" > /root/.ssh/temp_rsa',
        //"chmod 400 /root/.ssh/temp_rsa`,
        //'eval "$(ssh-agent -s)" && ssh-add /root/.ssh/temp_rsa',
        //"git submodule update --init --recursive",
        // Testing
        // Building
        "npm install",
      ],
      commands: [
        `npx sst build --stage ${scope.stage}`
      ],
      primaryOutputDirectory: ".build/cdk.out",
      rolePolicyStatements,
    })
    const pipeline = new CodePipeline(this, "Pipeline", {
      pipelineName: `${prefix}-pipeline`,
      synth,
      dockerEnabledForSynth: true,
      crossAccountKeys: false,
    })
    pipeline.addStage(new OutboundStage(this, "Stage"))
  }
}


class OutboundStage extends Stage {
  constructor(scope: sst.Stack, id: string, props?: StageProps) {
    super(scope, id, props);
    // Lack of support of CodePipeline in sst out-of-box. We pass in a Stage where sst.App is required.
    new OutboundStack(this, "Stack", {
      stackName: `${scope.stage}-tgr-warden-outbound-stack`
    });
  }
}