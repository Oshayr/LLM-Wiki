---
title: Neural Networks
type: concept
confidence: medium
sources:
  - url: https://h2o.ai/wiki/neural-network-architectures/
    title: "What are Neural Network Architectures? | H2O.ai"
  - url: https://www.v7labs.com/blog/neural-network-architectures-guide
    title: "The Essential Guide to Neural Network Architectures | V7 Labs"
  - url: https://codewave.com/insights/development-of-neural-networks-history/
    title: "History and Development of Neural Networks in AI | CodeWave"
  - url: https://medium.com/@kavyasrirelangi100/from-perceptrons-to-transformers-the-milestones-of-deep-learning-a97bc1b172ef
    title: "From Perceptrons to Transformers: The Milestones of Deep Learning"
  - url: https://www.dataversity.net/brief-history-deep-learning/
    title: "A Brief History of Deep Learning | Dataversity"
related: [[deep-learning]], [[machine-learning]], [[transformers]], [[convolutional-neural-networks]], [[backpropagation]], [[large-language-models]]
created: 2026-04-09
updated: 2026-04-09
---

# Neural Networks

![Neural network diagram showing layers of interconnected nodes](https://upload.wikimedia.org/wikipedia/commons/thumb/4/46/Colored_neural_network.svg/560px-Colored_neural_network.svg.png)

A **neural network** is a computational model loosely inspired by the structure of biological brains. It consists of interconnected layers of artificial "neurons" (nodes) that process numerical inputs, learn weighted connections through training, and produce outputs for tasks like classification, regression, generation, and decision-making. Neural networks are the foundational building block of [[deep-learning]].

## Overview

Neural networks power nearly every major advance in modern AI — from image recognition to language understanding to game-playing agents. They learn by adjusting internal parameters (weights and biases) to minimize prediction error on training data, a process formalized as [[backpropagation]] with gradient descent.

At a high level, a neural network is defined by:

- **Architecture** — the arrangement and type of layers
- **Activation functions** — nonlinear transformations applied at each neuron (e.g., ReLU, sigmoid, tanh)
- **Loss function** — a measure of prediction error that training tries to minimize
- **Optimizer** — the algorithm that updates weights (e.g., SGD, Adam)

Neural networks are the engine behind [[large-language-models]], [[convolutional-neural-networks]] for vision, and virtually all of modern [[deep-learning]] research.

## Key Concepts

### Layers

Every standard neural network is organized into three layer types:

| Layer | Role |
|---|---|
| **Input layer** | Receives raw data (pixels, token embeddings, sensor values) |
| **Hidden layer(s)** | Learns hierarchical feature representations |
| **Output layer** | Produces final predictions or class probabilities |

The number of hidden layers determines network "depth." A network with many hidden layers is called a *deep* neural network, giving rise to the term [[deep-learning]].

### Neurons and Weights

Each neuron computes a weighted sum of its inputs and passes the result through an activation function:

```
output = activation(Σ (weight_i × input_i) + bias)
```

Weights are the learnable parameters — during training, [[backpropagation]] computes gradients of the loss with respect to each weight and adjusts them incrementally.

### Activation Functions

Nonlinear activation functions are critical — without them, stacking layers would collapse to a single linear transformation. Common activations:

- **ReLU** (Rectified Linear Unit): `max(0, x)` — most widely used in hidden layers
- **Sigmoid**: maps output to (0, 1) — used in binary classification output layers
- **Softmax**: normalizes outputs to a probability distribution — used in multi-class output layers
- **Tanh**: maps to (-1, 1) — used in RNNs and older architectures

### Backpropagation

[[Backpropagation]] is the algorithm that trains neural networks. It applies the chain rule of calculus to compute how much each weight contributed to the total loss, enabling gradient-based updates. Introduced to widespread use by [Rumelhart, Hinton, and Williams in 1986](https://www.dataversity.net/brief-history-deep-learning/), backpropagation remains the standard training mechanism for virtually all neural networks.

## History and Milestones

Neural networks have a long history punctuated by breakthroughs and "AI winters":

| Year | Event |
|---|---|
| **1943** | McCulloch & Pitts publish the first mathematical model of a neuron using threshold logic |
| **1958** | Frank Rosenblatt develops the **Perceptron**, capable of binary classification |
| **1969** | Minsky & Papert's *Perceptrons* book highlights limitations, triggering the first AI winter |
| **1982** | Hopfield networks introduce recurrent connections for pattern storage and recall |
| **1986** | Rumelhart, Hinton & Williams popularize [[backpropagation]] for training multi-layer networks |
| **1989** | Yann LeCun applies backprop to [[convolutional-neural-networks]] (CNNs) for handwriting recognition |
| **1997** | Hochreiter & Schmidhuber introduce **LSTM**, solving the vanishing gradient problem in RNNs |
| **2012** | **AlexNet** wins ImageNet by a large margin using GPU-trained deep CNNs — the modern deep learning era begins |
| **2014** | Ian Goodfellow introduces **Generative Adversarial Networks (GANs)** |
| **2015** | **ResNet** introduces skip connections, enabling networks 100+ layers deep |
| **2017** | Google publishes "Attention Is All You Need," introducing the **[[Transformers\|Transformer]]** architecture |
| **2020** | OpenAI releases **GPT-3** (175B parameters), demonstrating the power of scaling [[large-language-models]] |

Sources: [CodeWave](https://codewave.com/insights/development-of-neural-networks-history/), [Dataversity](https://www.dataversity.net/brief-history-deep-learning/), [Medium — Perceptrons to Transformers](https://medium.com/@kavyasrirelangi100/from-perceptrons-to-transformers-the-milestones-of-deep-learning-a97bc1b172ef)

## Major Architecture Types

Modern neural networks come in many specialized forms. See [V7 Labs' architecture guide](https://www.v7labs.com/blog/neural-network-architectures-guide) for a comprehensive overview.

### Feedforward Networks (MLP)
The simplest form — data flows in one direction, from input to output. Also called **Multi-Layer Perceptrons (MLPs)**. Used for tabular data and as components within larger systems.

### Convolutional Neural Networks (CNNs)
Designed for spatial data (images, video). Use convolutional filters that slide across the input to detect local patterns (edges, textures, shapes), building up to complex features in deeper layers. See [[convolutional-neural-networks]].

### Recurrent Neural Networks (RNNs)
Process sequential data by maintaining a hidden state that is updated at each time step, effectively giving the network "memory." Used for time-series, audio, and early NLP tasks.

### Long Short-Term Memory (LSTM)
A specialized RNN with gating mechanisms (input, forget, output gates) that control what information is retained or discarded across long sequences. Solves the vanishing gradient problem that plagues vanilla RNNs.

### Transformers
Introduced in 2017, [[transformers]] replace recurrence with **self-attention** — allowing every token in a sequence to attend to every other token simultaneously. This parallelism enables training on massive datasets and is the foundation of modern [[large-language-models]] like GPT and BERT.

### Generative Adversarial Networks (GANs)
A two-network system: a **generator** produces fake samples; a **discriminator** tries to distinguish fake from real. Adversarial training pushes both to improve, resulting in highly realistic generated images, audio, and video.

### Graph Neural Networks (GNNs)
Operate on graph-structured data (molecules, social networks, knowledge graphs). Each node aggregates information from its neighbors iteratively.

## Training Neural Networks

Training a neural network involves:

1. **Forward pass** — input flows through layers to produce a prediction
2. **Loss computation** — compare prediction to ground truth using a loss function (e.g., cross-entropy, MSE)
3. **Backward pass** — [[backpropagation]] computes gradients of the loss w.r.t. each weight
4. **Weight update** — an optimizer (SGD, Adam, RMSProp) adjusts weights to reduce loss
5. **Repeat** for many iterations (epochs) over batches of training data

Key training challenges include:
- **Overfitting** — model memorizes training data; addressed with dropout, regularization, data augmentation
- **Vanishing/exploding gradients** — gradients become too small or large in deep networks; addressed with LSTM, skip connections, batch normalization
- **Compute cost** — large networks require significant GPU/TPU resources

## Applications

Neural networks are central to:

- **Computer vision** — image classification, object detection, segmentation, medical imaging
- **Natural language processing** — translation, summarization, question answering, [[large-language-models]]
- **Speech** — recognition (ASR), text-to-speech synthesis
- **Generative AI** — image synthesis (Stable Diffusion), music, video
- **Reinforcement learning** — game playing (AlphaGo), robotics, autonomous driving
- **Science** — protein structure prediction (AlphaFold), drug discovery, climate modeling

## See Also

- [[deep-learning]] — the broader field built on neural networks
- [[backpropagation]] — the algorithm used to train them
- [[convolutional-neural-networks]] — specialized for images
- [[transformers]] — the dominant architecture in modern NLP and vision
- [[large-language-models]] — scaled transformers trained on text
- [[machine-learning]] — the parent discipline

---

*Sources: [H2O.ai](https://h2o.ai/wiki/neural-network-architectures/) · [V7 Labs](https://www.v7labs.com/blog/neural-network-architectures-guide) · [CodeWave History](https://codewave.com/insights/development-of-neural-networks-history/) · [Dataversity](https://www.dataversity.net/brief-history-deep-learning/) · [Medium](https://medium.com/@kavyasrirelangi100/from-perceptrons-to-transformers-the-milestones-of-deep-learning-a97bc1b172ef)*
