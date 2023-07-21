package com.datastax.oss.sga.model.parser;

import com.datastax.oss.sga.api.model.AgentConfiguration;
import com.datastax.oss.sga.api.model.Application;
import com.datastax.oss.sga.api.model.Module;
import com.datastax.oss.sga.api.model.Pipeline;
import com.datastax.oss.sga.impl.parser.ModelBuilder;
import org.junit.jupiter.api.Test;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

public class ResourcesSpecsTest {

    @Test
    public void testConfigureResourceSpecs() throws Exception {
        Application applicationInstance = ModelBuilder
                .buildApplicationInstance(Map.of("instance.yaml",
                        buildInstanceYaml(),
                        "module.yaml", """
                                module: "module-1"
                                id: "pipeline-1"
                                resources:
                                   parallelism: 7
                                   size: 7             
                                topics:
                                  - name: "input-topic"
                                    creation-mode: create-if-not-exists
                                pipeline:
                                  - name: "step1"                                    
                                    type: "noop"
                                    input: "input-topic"                                    
                                  - name: "step2"
                                    type: "noop"
                                    resources:
                                       parallelism: 2
                                  - name: "step3"
                                    type: "noop"
                                    resources:
                                       size: 3                                      
                                  - name: "step3"
                                    type: "noop"
                                    resources:
                                       size: 3
                                       parallelism: 5
                                """,
                        "module2.yaml", """
                                module: "module-2"
                                id: "pipeline-2"             
                                topics:
                                  - name: "input-topic"
                                    creation-mode: create-if-not-exists
                                pipeline:
                                  - name: "step1"                                    
                                    type: "noop"
                                    input: "input-topic"                                    
                                  - name: "step2"
                                    type: "noop"
                                    resources:
                                       parallelism: 2
                                  - name: "step3"
                                    type: "noop"
                                    resources:
                                       size: 3                                      
                                  - name: "step3"
                                    type: "noop"
                                    resources:
                                       size: 3
                                       parallelism: 5
                                """));

        {
            Module module = applicationInstance.getModule("module-1");
            Pipeline pipeline = module.getPipelines().get("pipeline-1");

            AgentConfiguration agent1 = pipeline.getAgents().get(0);
            assertNotNull(agent1.getResources());
            assertEquals(7, agent1.getResources().parallelism());
            assertEquals(7, agent1.getResources().size());

            AgentConfiguration agent2 = pipeline.getAgents().get(1);
            assertNotNull(agent2.getResources());
            assertEquals(2, agent2.getResources().parallelism());
            assertEquals(7, agent2.getResources().size());

            AgentConfiguration agent3 = pipeline.getAgents().get(2);
            assertNotNull(agent3.getResources());
            assertEquals(7, agent3.getResources().parallelism());
            assertEquals(3, agent3.getResources().size());
        }

        {
            Module module = applicationInstance.getModule("module-2");
            Pipeline pipeline = module.getPipelines().get("pipeline-2");

            AgentConfiguration agent1 = pipeline.getAgents().get(0);
            assertNotNull(agent1.getResources());
            assertEquals(1, agent1.getResources().parallelism());
            assertEquals(1, agent1.getResources().size());

            AgentConfiguration agent2 = pipeline.getAgents().get(1);
            assertNotNull(agent2.getResources());
            assertEquals(2, agent2.getResources().parallelism());
            assertEquals(1, agent2.getResources().size());

            AgentConfiguration agent3 = pipeline.getAgents().get(2);
            assertNotNull(agent3.getResources());
            assertEquals(1, agent3.getResources().parallelism());
            assertEquals(3, agent3.getResources().size());
        }

    }

    private static String buildInstanceYaml() {
        return """
                instance:
                  streamingCluster:
                    type: "noop"
                  computeCluster:
                    type: "none"
                """;
    }
}