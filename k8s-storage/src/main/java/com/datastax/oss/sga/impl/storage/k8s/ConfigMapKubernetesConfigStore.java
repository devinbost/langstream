package com.datastax.oss.sga.impl.storage.k8s;

import io.fabric8.kubernetes.api.model.ConfigMap;
import io.fabric8.kubernetes.api.model.ConfigMapBuilder;
import io.fabric8.kubernetes.api.model.HasMetadata;
import io.fabric8.kubernetes.api.model.KubernetesResourceList;
import io.fabric8.kubernetes.client.dsl.MixedOperation;
import io.fabric8.kubernetes.client.dsl.Resource;
import java.util.Map;

public class ConfigMapKubernetesConfigStore extends AbstractKubernetesConfigStore<ConfigMap> {

    @Override
    public boolean acceptScope(Scope scope) {
        return scope == Scope.CONFIGS;
    }

    @Override
    protected ConfigMap createResource(String key, String value) {
        return new ConfigMapBuilder()
                .withData(Map.of("value", value))
                .build();
    }

    @Override
    protected MixedOperation<ConfigMap, ? extends KubernetesResourceList<ConfigMap>, Resource<ConfigMap>> operation() {
        return client.configMaps();
    }

    @Override
    protected String get(String key, ConfigMap resource) {
        return resource.getData().get("value");
    }
}