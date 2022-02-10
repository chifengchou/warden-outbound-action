# Getting Started with Serverless Stack (SST)

This project was bootstrapped with [Create Serverless Stack](https://docs.serverless-stack.com/packages/create-serverless-stack).

Start by installing the dependencies.

```bash
$ npm install
```

## Prequisite to work effectively in this repo
- Ensure Python is properly configured in your system
- Ensure `saml2aws` has been properly configured in your system
- Ensure `pipenv` is installed in your system
- Ensure `aws` credentials properly configured in your system
- Ensure `pre-commit` has been properly configured in your system
- Ensure `commitizen` has been properly configured in your system
- Ensure `sentry-cli` has been properly configured in your system
- [Optional] Ensure your terminal can handle `venv` and cli `env`

## Commands


Stage names `dev`, `staging` and `prod` are reserved for deploying CI/CD pipeline stack.

You can use other stage names to develop/deploy application stack.


### Application stack
* `npx sst start --stage ${your_stage}`: Starts the local application development environment.
* `npx sst build --stage ${your_stage}`: Build and synthesize the application stack.
* `npx sst deploy --stage ${your_stage}`: Deploy application to AWS.

### CICD/Pipeline stack
* `npx sst build --stage dev|staging|prod`: Build and synthesize the CICD stack.
* `npx sst deploy --stage dev|staging|prod`: Deploy CICD AWS.



## Documentation

Learn more about the Serverless Stack.

- [Docs](https://docs.serverless-stack.com)
- [@serverless-stack/cli](https://docs.serverless-stack.com/packages/cli)
- [@serverless-stack/resources](https://docs.serverless-stack.com/packages/resources)

